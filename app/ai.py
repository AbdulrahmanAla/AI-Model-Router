"""Optional, server-side AI explanations and fallback answers."""

from __future__ import annotations

import ast
import asyncio
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
import sympy as sp

from .solver import GrammarError, _has_variable_denominator, parse_constant, parse_expression


_AI_CONCURRENCY = threading.BoundedSemaphore(2)
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


@dataclass(frozen=True)
class ProviderConfig:
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
    base_url = os.getenv("AI_BASE_URL", "").strip()
    api_key = os.getenv("AI_API_KEY", "").strip()
    model = os.getenv("AI_MODEL", "").strip()
    if not base_url or not api_key or not model:
        return None
    return ProviderConfig(
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        model=model,
        timeout_seconds=_number_setting(
            "AI_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS, minimum=0.1, maximum=120.0
        ),
        max_tokens=_integer_setting("AI_MAX_TOKENS", _DEFAULT_MAX_TOKENS, minimum=1, maximum=4000),
    )


def _metrics(
    *,
    started: float,
    provider_started: float | None,
    status: str,
    model: str | None,
    ai_calls: int,
    solver_ms: float | None = None,
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    usage = usage or {}

    def token(name: str) -> int | None:
        value = usage.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return None

    return {
        "route": "ai",
        "ai_calls": ai_calls,
        "solver_ms": solver_ms,
        "ai_latency_ms": round((time.perf_counter() - provider_started) * 1000, 3)
        if provider_started is not None
        else None,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "model": model,
        "input_tokens": token("prompt_tokens"),
        "output_tokens": token("completion_tokens"),
        "total_tokens": token("total_tokens"),
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
        ),
    )


def _chat_url(base_url: str) -> str:
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def _validate_grammar(payload: dict[str, Any]) -> None:
    """Validate the same bounded grammar without running a full exact solve."""
    operation = payload["operation"]
    expression = payload["expression"]
    if operation == "equation":
        if expression.count("=") > 1:
            raise GrammarError("An equation may contain one equals sign.")
        if "=" in expression:
            left_source, right_source = expression.split("=", 1)
            left = parse_expression(left_source)
            right = parse_expression(right_source)
            left_tree = ast.parse(left_source.replace("^", "**"), mode="eval")
            right_tree = ast.parse(right_source.replace("^", "**"), mode="eval")
            if _has_variable_denominator(left_tree.body) or _has_variable_denominator(right_tree.body):
                raise GrammarError("Equations with a variable in a denominator are not supported.")
            equation = sp.expand(left.expression - right.expression)
        else:
            parsed = parse_expression(expression)
            if _has_variable_denominator(parsed.tree.body):
                raise GrammarError("Equations with a variable in a denominator are not supported.")
            equation = sp.expand(parsed.expression)
        try:
            sp.Poly(equation, sp.Symbol("x", real=True))
        except Exception as exc:
            raise GrammarError("Equations must be real polynomials in x.") from exc
        return

    parse_expression(expression)
    if operation == "integral" and payload.get("lower") is not None:
        parse_constant(payload["lower"])
        parse_constant(payload["upper"])
    if operation == "limit":
        parse_constant(payload["target"])


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
    return [
        {
            "role": "system",
            "content": (
                "Answer the structured math request. Return exactly one JSON object and no prose, markdown, "
                "or code fences. The object must have exactly these keys: status and result. "
                "status is solved, unresolved, or rejected. Use a formula string for a solved calculus answer. "
                "Use a sorted JSON array of real root strings for a solved equation. Use result null for unresolved or rejected."
            ),
        },
        {"role": "user", "content": f"Structured request: {request_text}"},
    ]


def _machine_answer_is_valid(text: str, operation: str) -> bool:
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
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise ValueError("response text is incomplete")
    content = message["content"].strip()
    if not content or len(content) > 12000:
        raise ValueError("response text is empty or too large")
    if action in {"baseline", "fallback"} and not _machine_answer_is_valid(content, operation):
        raise ValueError("response does not match the JSON answer contract")
    return content


def _usage(body: Any) -> dict[str, Any]:
    value = body.get("usage") if isinstance(body, dict) else None
    return value if isinstance(value, dict) else {}


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
    try:
        transport = getattr(app.state, "ai_transport", None)
        request_body = {
            "model": config.model,
            "messages": _messages(action, payload, exact),
            "max_tokens": config.max_tokens,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}
        attempted = True
        async with httpx.AsyncClient(transport=transport, timeout=config.timeout_seconds) as client:
            response = await client.post(_chat_url(config.base_url), headers=headers, json=request_body)
    except httpx.TimeoutException as exc:
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
    usage = _usage(response_body)
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
        text = _response_content(body, action, payload["operation"])
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


async def handle_ai(app: Any, action: str, request: Any, validated_payload: dict[str, Any]) -> dict[str, Any]:
    """Validate, optionally recompute, and make one provider request."""
    if action not in _ALLOWED_ACTIONS:
        raise GrammarError("That AI action is not supported.")
    _validate_grammar(validated_payload)
    started = time.perf_counter()
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
