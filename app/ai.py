"""Optional, server-side AI explanations and fallback answers."""

from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
from .solver import (
    GrammarError,
    SOLVER_TIMEOUT_MS,
    parse_constant,
    validate_structured_payload,
)


_AI_CONCURRENCY = threading.BoundedSemaphore(2)
_GRAMMAR_CONCURRENCY = threading.BoundedSemaphore(2)
GRAMMAR_TIMEOUT_MS = int(os.getenv("AI_GRAMMAR_TIMEOUT_MS", str(SOLVER_TIMEOUT_MS)))
_DEFAULT_TIMEOUT_SECONDS = 20.0
_DEFAULT_MAX_TOKENS = 700
_ALLOWED_ACTIONS = {"explain", "fallback", "baseline"}


class AIServiceError(RuntimeError):
    """A safe, browser-facing AI service error with redacted details."""

    def __init__(self, status_code: int, code: str, detail: str, metrics: dict[str, Any]):
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.metrics = metrics


class AIValidationBusy(GrammarError):
    """The bounded grammar-validation worker pool has no free slot."""


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float
    max_tokens: int


def _number_setting(name: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    if value != value or value in (float("inf"), float("-inf")):
        return default
    return max(minimum, min(maximum, value))


def _integer_setting(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _provider_config() -> ProviderConfig | None:
    provider = os.getenv("AI_PROVIDER", "openai").strip().lower() or "openai"
    if provider == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip()
        api_key = ""
        model = os.getenv("OLLAMA_MODEL", "").strip()
    elif provider in {"openai", "openai-compatible"}:
        provider = "openai"
        base_url = os.getenv("AI_BASE_URL", "").strip()
        api_key = os.getenv("AI_API_KEY", "").strip()
        model = os.getenv("AI_MODEL", "").strip()
    else:
        return None
    if not base_url or not model or (provider == "openai" and not api_key):
        return None
    timeout_default = 120.0 if provider == "ollama" else _DEFAULT_TIMEOUT_SECONDS
    if provider == "ollama" and "AI_TIMEOUT_SECONDS" in os.environ:
        timeout_default = _number_setting(
            "AI_TIMEOUT_SECONDS", timeout_default, minimum=0.1, maximum=120.0
        )
    timeout_name = "OLLAMA_TIMEOUT_SECONDS" if provider == "ollama" else "AI_TIMEOUT_SECONDS"
    return ProviderConfig(
        provider=provider,
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        model=model,
        timeout_seconds=_number_setting(timeout_name, timeout_default, minimum=0.1, maximum=120.0),
        max_tokens=_integer_setting("AI_MAX_TOKENS", _DEFAULT_MAX_TOKENS, minimum=1, maximum=4000),
    )


def ai_configured() -> bool:
    """Return whether the selected provider has the minimum local config."""
    return _provider_config() is not None


def _metrics(
    *,
    started: float,
    provider_started: float | None,
    status: str,
    model: str | None,
    ai_calls: int,
    solver_ms: float | None = None,
    usage: dict[str, Any] | None = None,
    route: str = "ai",
) -> dict[str, Any]:
    usage = usage or {}

    def token(name: str) -> int | None:
        value = usage.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return None

    def duration_ns(name: str) -> int | None:
        value = usage.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return None

    input_tokens = token("prompt_tokens")
    output_tokens = token("completion_tokens")
    total_tokens = token("total_tokens")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    return {
        "route": route,
        "ai_calls": ai_calls,
        "solver_ms": solver_ms,
        "ai_latency_ms": round((time.perf_counter() - provider_started) * 1000, 3)
        if provider_started is not None
        else None,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "prompt_eval_count": token("prompt_eval_count"),
        "eval_count": token("eval_count"),
        "total_duration_ns": duration_ns("total_duration"),
        "load_duration_ns": duration_ns("load_duration"),
        "prompt_eval_duration_ns": duration_ns("prompt_eval_duration"),
        "eval_duration_ns": duration_ns("eval_duration"),
        "ai_status": status,
    }


def _error(
    *,
    status_code: int,
    code: str,
    detail: str,
    started: float,
    provider_started: float | None,
    status: str,
    model: str | None,
    ai_calls: int,
    solver_ms: float | None = None,
    usage: dict[str, Any] | None = None,
    route: str = "ai",
) -> AIServiceError:
    return AIServiceError(
        status_code,
        code,
        detail,
        _metrics(
            started=started,
            provider_started=provider_started,
            status=status,
            model=model,
            ai_calls=ai_calls,
            solver_ms=solver_ms,
            usage=usage,
            route=route,
        ),
    )


def _chat_url(base_url: str) -> str:
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def _ollama_url(base_url: str) -> str:
    if base_url.endswith("/api/chat"):
        return base_url
    return f"{base_url}/api/chat"


def _validate_grammar(payload: dict[str, Any]) -> None:
    """Validate the same bounded grammar without running a full exact solve."""
    validate_structured_payload(payload)


def _grammar_worker(payload: dict[str, Any], result_queue: Any) -> None:
    try:
        _validate_grammar(payload)
        result_queue.put({"ok": True})
    except GrammarError as exc:
        result_queue.put({"ok": False, "message": str(exc)})
    except Exception:
        result_queue.put({"ok": False, "message": "The structured input could not be validated safely."})


def _validate_grammar_bounded(payload: dict[str, Any]) -> None:
    """Run grammar parsing and SymPy construction outside the request loop."""
    if not _GRAMMAR_CONCURRENCY.acquire(blocking=False):
        raise AIValidationBusy("Structured input validation is busy. Try again shortly.")
    result_queue = None
    try:
        context = mp.get_context("spawn")
        result_queue = context.Queue(maxsize=1)
        process = context.Process(target=_grammar_worker, args=(payload, result_queue), daemon=True)
        process.start()
        process.join(GRAMMAR_TIMEOUT_MS / 1000)
        if process.is_alive():
            process.terminate()
            process.join(0.2)
            raise GrammarError("Structured input validation reached its time limit.")
        try:
            result = result_queue.get(timeout=0.25)
        except queue.Empty as exc:
            raise GrammarError("Structured input validation did not finish safely.") from exc
        if not result.get("ok"):
            raise GrammarError(result.get("message", "The structured input is outside the supported grammar."))
    finally:
        if result_queue is not None:
            result_queue.close()
        _GRAMMAR_CONCURRENCY.release()


def _messages(action: str, payload: dict[str, Any], exact: dict[str, Any] | None) -> list[dict[str, str]]:
    request_text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if action == "explain":
        exact_text = json.dumps(
            {
                "operation": exact["operation"],
                "expression": exact["expression"],
                "result": exact["result"],
                "verification": exact["verification"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return [
            {
                "role": "system",
                "content": (
                    "You are an optional math tutor. Explain the supplied exact result in concise plain text. "
                    "Do not change the result or claim that numerical evidence is a proof. "
                    "Mention the supplied check status when it matters."
                ),
            },
            {"role": "user", "content": f"Structured request: {request_text}\nExact result and check: {exact_text}"},
        ]
    equation_contract = (
        "Use a sorted JSON array of real root strings for a solved polynomial equation, or the exact sentinels "
        "all real x and no real solutions."
    )
    if action == "fallback":
        equation_contract += " For a non-polynomial equation, a short unverified result string may describe a symbolic family."
    return [
        {
            "role": "system",
            "content": (
                "Answer the structured math request. Return exactly one JSON object and no prose, markdown, "
                "or code fences. The object must have exactly these keys: status and result. "
                "The variable is real x. For a solved derivative, limit, or integral, use a typed formula string; "
                "omit an arbitrary integration constant C. "
                f"{equation_contract} status is solved, unresolved, or rejected, and result is null for unresolved "
                "or rejected."
            ),
        },
        {"role": "user", "content": f"Structured request: {request_text}"},
    ]


def _machine_answer_is_valid(text: str, operation: str, action: str) -> bool:
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(value, dict) or set(value) != {"status", "result"}:
        return False
    status = value.get("status")
    result = value.get("result")
    if status not in {"solved", "unresolved", "rejected"}:
        return False
    if status in {"unresolved", "rejected"}:
        return result is None
    if operation == "equation":
        if action == "fallback" and isinstance(result, str) and result.strip() and len(result) <= 1000:
            return True
        if isinstance(result, str) and result in {"all real x", "no real solutions"}:
            return True
        if not isinstance(result, list) or any(not isinstance(item, str) or not item.strip() for item in result):
            return False
        try:
            parsed = [parse_constant(item) for item in result]
        except (GrammarError, TypeError, KeyError):
            return False
        if not all(item.is_real is True and item.is_finite is True for item in parsed):
            return False
        values = [float(item) for item in parsed]
        return values == sorted(values)
    return isinstance(result, str) and bool(result.strip()) and len(result) <= 1000


def _response_content(body: Any, action: str, operation: str) -> str:
    if not isinstance(body, dict):
        raise ValueError("response body is not an object")
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("response choices are incomplete")
    choice = choices[0]
    if choice.get("finish_reason") == "length":
        raise ValueError("response was truncated")
    message = choice.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise ValueError("response text is incomplete")
    content = message["content"].strip()
    if not content or len(content) > 12000:
        raise ValueError("response text is empty or too large")
    if action in {"baseline", "fallback"} and not _machine_answer_is_valid(content, operation, action):
        raise ValueError("response does not match the JSON answer contract")
    return content


def _ollama_response_content(body: Any, action: str, operation: str) -> str:
    if not isinstance(body, dict):
        raise ValueError("response body is not an object")
    message = body.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise ValueError("response message is incomplete")
    content = message["content"].strip()
    if not content or len(content) > 12000:
        raise ValueError("response text is empty or too large")
    if action in {"baseline", "fallback"} and not _machine_answer_is_valid(content, operation, action):
        raise ValueError("response does not match the JSON answer contract")
    return content


def _usage(body: Any) -> dict[str, Any]:
    value = body.get("usage") if isinstance(body, dict) else None
    return value if isinstance(value, dict) else {}


def _ollama_usage(body: Any) -> dict[str, Any]:
    """Normalize Ollama's native counts and nanosecond durations."""
    if not isinstance(body, dict):
        return {}
    prompt_count = body.get("prompt_eval_count")
    eval_count = body.get("eval_count")
    usage: dict[str, Any] = {
        "prompt_eval_count": prompt_count,
        "eval_count": eval_count,
        "prompt_eval_duration": body.get("prompt_eval_duration"),
        "eval_duration": body.get("eval_duration"),
        "load_duration": body.get("load_duration"),
        "total_duration": body.get("total_duration"),
    }
    if isinstance(prompt_count, int) and not isinstance(prompt_count, bool) and prompt_count >= 0:
        usage["prompt_tokens"] = prompt_count
    if isinstance(eval_count, int) and not isinstance(eval_count, bool) and eval_count >= 0:
        usage["completion_tokens"] = eval_count
    if (
        isinstance(prompt_count, int)
        and not isinstance(prompt_count, bool)
        and prompt_count >= 0
        and isinstance(eval_count, int)
        and not isinstance(eval_count, bool)
        and eval_count >= 0
    ):
        usage["total_tokens"] = prompt_count + eval_count
    return usage


async def _call_provider(
    app: Any,
    *,
    action: str,
    payload: dict[str, Any],
    exact: dict[str, Any] | None,
    started: float,
    solver_ms: float | None,
) -> dict[str, Any]:
    config = _provider_config()
    if config is None:
        raise _error(
            status_code=503,
            code="ai_unavailable",
            detail="The AI provider is not configured.",
            started=started,
            provider_started=None,
            status="missing_config",
            model=None,
            ai_calls=0,
            solver_ms=solver_ms,
        )
    acquired = await asyncio.to_thread(_AI_CONCURRENCY.acquire, False)
    if not acquired:
        raise _error(
            status_code=503,
            code="ai_unavailable",
            detail="The AI provider is busy. Try again shortly.",
            started=started,
            provider_started=None,
            status="busy",
            model=config.model,
            ai_calls=0,
            solver_ms=solver_ms,
        )

    provider_started = time.perf_counter()
    attempted = False
    transport = getattr(app.state, "ai_transport", None)
    if config.provider == "ollama":
        request_body = {
            "model": config.model,
            "messages": _messages(action, payload, exact),
            "stream": False,
            "think": False,
            "options": {"num_predict": config.max_tokens},
        }
        endpoint = _ollama_url(config.base_url)
        headers = {"Content-Type": "application/json"}
    else:
        request_body = {
            "model": config.model,
            "messages": _messages(action, payload, exact),
            "max_tokens": config.max_tokens,
            "stream": False,
        }
        endpoint = _chat_url(config.base_url)
        headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(transport=transport, timeout=config.timeout_seconds) as client:
            return await client.post(endpoint, headers=headers, json=request_body)

    try:
        attempted = True
        response = await asyncio.wait_for(send_request(), timeout=config.timeout_seconds)
    except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
        raise _error(
            status_code=504,
            code="ai_unavailable",
            detail="The AI provider did not respond before the deadline.",
            started=started,
            provider_started=provider_started,
            status="timeout",
            model=config.model,
            ai_calls=1 if attempted else 0,
            solver_ms=solver_ms,
        ) from exc
    except httpx.RequestError as exc:
        raise _error(
            status_code=502,
            code="ai_unavailable",
            detail="The AI provider could not be reached.",
            started=started,
            provider_started=provider_started,
            status="connection_error",
            model=config.model,
            ai_calls=1 if attempted else 0,
            solver_ms=solver_ms,
        ) from exc
    finally:
        _AI_CONCURRENCY.release()

    try:
        response_body = response.json()
    except (ValueError, json.JSONDecodeError):
        response_body = {}
    usage = _ollama_usage(response_body) if config.provider == "ollama" else _usage(response_body)
    if response.status_code < 200 or response.status_code >= 300:
        status = "auth_error" if response.status_code in {401, 403} else "rate_limited" if response.status_code == 429 else "provider_error"
        raise _error(
            status_code=502,
            code="ai_unavailable",
            detail="The AI provider returned an error.",
            started=started,
            provider_started=provider_started,
            status=status,
            model=config.model,
            ai_calls=1,
            solver_ms=solver_ms,
            usage=usage,
        )
    try:
        body = response_body
        text = (
            _ollama_response_content(body, action, payload["operation"])
            if config.provider == "ollama"
            else _response_content(body, action, payload["operation"])
        )
    except (ValueError, json.JSONDecodeError, TypeError) as exc:
        raise _error(
            status_code=502,
            code="ai_unavailable",
            detail="The AI provider returned an incomplete response.",
            started=started,
            provider_started=provider_started,
            status="invalid_response",
            model=config.model,
            ai_calls=1,
            solver_ms=solver_ms,
            usage=usage,
        ) from exc
    return {
        "status": "answered",
        "text": text,
        "verification": {"status": "not_checked", "method": "AI output", "detail": "AI text is unverified."},
        "metrics": _metrics(
            started=started,
            provider_started=provider_started,
            status="ok",
            model=config.model,
            ai_calls=1,
            solver_ms=solver_ms,
            usage=usage,
        ),
    }


async def call_ollama(
    app: Any,
    prompt: str,
    *,
    action: str = "route",
    structured_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send one bounded plain-language prompt to the configured local Ollama server.

    This is the narrow seam used by the routed endpoint. It never accepts a
    browser-provided provider URL or credential and it never runs the solver.
    ``structured_payload`` is optional context for a future router prompt and
    is deliberately serialized as data inside the user message.
    """
    started = time.perf_counter()
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12_000:
        raise _error(
            status_code=422,
            code="invalid_prompt",
            detail="The AI prompt is empty or too large.",
            started=started,
            provider_started=None,
            status="invalid_prompt",
            model=None,
            ai_calls=0,
            route="ollama",
        )
    config = _provider_config()
    if config is None or config.provider != "ollama":
        raise _error(
            status_code=503,
            code="ai_unavailable",
            detail="The local AI provider is not configured.",
            started=started,
            provider_started=None,
            status="missing_config",
            model=None,
            ai_calls=0,
            route="ollama",
        )
    acquired = await asyncio.to_thread(_AI_CONCURRENCY.acquire, False)
    if not acquired:
        raise _error(
            status_code=503,
            code="ai_unavailable",
            detail="The local AI provider is busy. Try again shortly.",
            started=started,
            provider_started=None,
            status="busy",
            model=config.model,
            ai_calls=0,
            route="ollama",
        )

    provider_started = time.perf_counter()
    attempted = False
    transport = getattr(app.state, "ai_transport", None)
    context = ""
    if structured_payload is not None:
        context = "\nStructured context: " + json.dumps(
            structured_payload, sort_keys=True, separators=(",", ":")
        )
    request_body = {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an optional AI assistant. Return concise plain text. "
                    "Do not claim that an unverified answer is a proof."
                ),
            },
            {"role": "user", "content": prompt.strip() + context},
        ],
        "stream": False,
        "think": False,
        "options": {"num_predict": config.max_tokens},
    }
    headers = {"Content-Type": "application/json"}
    endpoint = _ollama_url(config.base_url)

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(transport=transport, timeout=config.timeout_seconds) as client:
            return await client.post(endpoint, headers=headers, json=request_body)

    try:
        attempted = True
        response = await asyncio.wait_for(send_request(), timeout=config.timeout_seconds)
    except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
        raise _error(
            status_code=504,
            code="ai_unavailable",
            detail="The local AI provider did not respond before the deadline.",
            started=started,
            provider_started=provider_started,
            status="timeout",
            model=config.model,
            ai_calls=1 if attempted else 0,
            route="ollama",
        ) from exc
    except httpx.RequestError as exc:
        raise _error(
            status_code=502,
            code="ai_unavailable",
            detail="The local AI provider could not be reached.",
            started=started,
            provider_started=provider_started,
            status="connection_error",
            model=config.model,
            ai_calls=1 if attempted else 0,
            route="ollama",
        ) from exc
    finally:
        _AI_CONCURRENCY.release()

    try:
        response_body = response.json()
    except (ValueError, json.JSONDecodeError):
        response_body = {}
    usage = _ollama_usage(response_body)
    if response.status_code < 200 or response.status_code >= 300:
        raise _error(
            status_code=502,
            code="ai_unavailable",
            detail="The local AI provider returned an error.",
            started=started,
            provider_started=provider_started,
            status="provider_error",
            model=config.model,
            ai_calls=1,
            usage=usage,
            route="ollama",
        )
    try:
        text = _ollama_response_content(response_body, action, "unknown")
    except (ValueError, json.JSONDecodeError, TypeError) as exc:
        raise _error(
            status_code=502,
            code="ai_unavailable",
            detail="The local AI provider returned an incomplete response.",
            started=started,
            provider_started=provider_started,
            status="invalid_response",
            model=config.model,
            ai_calls=1,
            usage=usage,
            route="ollama",
        ) from exc
    return {
        "status": "answered",
        "text": text,
        "verification": {"status": "not_checked", "method": "AI output", "detail": "AI text is unverified."},
        "metrics": _metrics(
            started=started,
            provider_started=provider_started,
            status="ok",
            model=config.model,
            ai_calls=1,
            usage=usage,
            route="ollama",
        ),
    }


async def call_text_prompt(app: Any, prompt: str, *, structured_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send a bounded language prompt through the configured provider."""
    config = _provider_config()
    if config is None:
        started = time.perf_counter()
        raise _error(status_code=503, code="ai_unavailable", detail="The AI provider is not configured.",
                     started=started, provider_started=None, status="missing_config", model=None, ai_calls=0)
    if config.provider == "ollama":
        return await call_ollama(app, prompt, structured_payload=structured_payload)
    started = time.perf_counter()
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12_000:
        raise _error(status_code=422, code="invalid_prompt", detail="The AI prompt is empty or too large.",
                     started=started, provider_started=None, status="invalid_prompt", model=None, ai_calls=0)
    acquired = await asyncio.to_thread(_AI_CONCURRENCY.acquire, False)
    if not acquired:
        raise _error(status_code=503, code="ai_unavailable", detail="The AI provider is busy. Try again shortly.",
                     started=started, provider_started=None, status="busy", model=config.model, ai_calls=0)
    provider_started = time.perf_counter()
    context = ""
    if structured_payload is not None:
        context = "\nStructured context: " + json.dumps(structured_payload, sort_keys=True, separators=(",", ":"))
    body = {"model": config.model, "messages": [
        {"role": "system", "content": "You are an optional AI assistant. Return concise plain text. Do not claim an unverified answer is a proof."},
        {"role": "user", "content": prompt.strip() + context},
    ], "max_tokens": config.max_tokens, "stream": False}
    headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}
    transport = getattr(app.state, "ai_transport", None)
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(transport=transport, timeout=config.timeout_seconds) as client:
            return await client.post(_chat_url(config.base_url), headers=headers, json=body)
    try:
        response = await asyncio.wait_for(send(), timeout=config.timeout_seconds)
    except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
        raise _error(status_code=504, code="ai_unavailable", detail="The AI provider did not respond before the deadline.",
                     started=started, provider_started=provider_started, status="timeout", model=config.model, ai_calls=1) from exc
    except httpx.RequestError as exc:
        raise _error(status_code=502, code="ai_unavailable", detail="The AI provider could not be reached.",
                     started=started, provider_started=provider_started, status="connection_error", model=config.model, ai_calls=1) from exc
    finally:
        _AI_CONCURRENCY.release()
    try:
        response_body = response.json()
    except (ValueError, json.JSONDecodeError):
        response_body = {}
    usage = _usage(response_body)
    if response.status_code < 200 or response.status_code >= 300:
        raise _error(status_code=502, code="ai_unavailable", detail="The AI provider returned an error.",
                     started=started, provider_started=provider_started, status="provider_error", model=config.model, ai_calls=1, usage=usage)
    try:
        text = _response_content(response_body, "explain", "unknown")
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise _error(status_code=502, code="ai_unavailable", detail="The AI provider returned an incomplete response.",
                     started=started, provider_started=provider_started, status="invalid_response", model=config.model, ai_calls=1, usage=usage) from exc
    return {"status": "answered", "text": text,
            "verification": {"status": "not_checked", "method": "AI output", "detail": "AI text is unverified."},
            "metrics": _metrics(started=started, provider_started=provider_started, status="ok", model=config.model, ai_calls=1, usage=usage)}


async def handle_ai(app: Any, action: str, request: Any, validated_payload: dict[str, Any]) -> dict[str, Any]:
    """Validate, optionally recompute, and make one provider request."""
    if action not in _ALLOWED_ACTIONS:
        raise GrammarError("That AI action is not supported.")
    started = time.perf_counter()
    await asyncio.to_thread(_validate_grammar_bounded, validated_payload)
    exact: dict[str, Any] | None = None
    solver_ms: float | None = None
    if action == "explain":
        from .main import solve_request

        exact = await solve_request(request)
        if exact.get("status") != "solved" or exact.get("result") is None:
            raise _error(
                status_code=409,
                code="explanation_unavailable",
                detail="The exact solver did not produce a result to explain.",
                started=started,
                provider_started=None,
                status="solver_unresolved",
                model=None,
                ai_calls=0,
            )
        solver_ms = exact.get("metrics", {}).get("solver_ms")
    return await _call_provider(
        app,
        action=action,
        payload=validated_payload,
        exact=exact,
        started=started,
        solver_ms=solver_ms,
    )
