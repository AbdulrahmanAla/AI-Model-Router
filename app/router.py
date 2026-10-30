"""Bounded route selection for the optional Jev decision model."""

from __future__ import annotations

import asyncio
import json
import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx

ROUTE_CHOICES = {"solver", "ai", "refuse"}
_JEV_CONCURRENCY = threading.BoundedSemaphore(2)
_DEFAULT_JEV_URL = "https://api.typesafe.ai/v1/systemone"
_DEFAULT_JEV_MODEL = "jev-latest"
_DEFAULT_JEV_TIMEOUT = 4.0
_MAX_PROMPT_LENGTH = 2000


class RouterError(RuntimeError):
    """A safe route-selection failure that can be represented in metadata."""


@dataclass(frozen=True)
class JevConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float


def _jev_config() -> JevConfig | None:
    key = os.getenv("TYPESAFE_API_KEY", "").strip()
    if not key:
        return None
    raw_timeout = os.getenv("JEV_TIMEOUT_SECONDS", str(_DEFAULT_JEV_TIMEOUT))
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError):
        timeout = _DEFAULT_JEV_TIMEOUT
    if not math.isfinite(timeout):
        timeout = _DEFAULT_JEV_TIMEOUT
    timeout = max(0.1, min(timeout, 20.0))
    return JevConfig(
        base_url=os.getenv("JEV_BASE_URL", _DEFAULT_JEV_URL).strip().rstrip("/"),
        api_key=key,
        model=os.getenv("JEV_MODEL", _DEFAULT_JEV_MODEL).strip() or _DEFAULT_JEV_MODEL,
        timeout_seconds=timeout,
    )


def _token(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _usage(body: Any) -> dict[str, int | None]:
    usage = body.get("usage") if isinstance(body, dict) else None
    if not isinstance(usage, dict):
        usage = {}
    input_tokens = _token(usage.get("input_tokens"))
    output_tokens = _token(usage.get("output_tokens"))
    total = _token(usage.get("total_tokens"))
    if total is None and input_tokens is not None and output_tokens is not None:
        total = input_tokens + output_tokens
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total}


def _route_question() -> dict[str, Any]:
    return {
        "type": "choice",
        "instructions": (
            "Choose the least expensive safe route for this request. Use solver only for "
            "supported structured math; use ai for language or explanation work; refuse "
            "when neither is safe."
        ),
        "criteria": {
            "solver": "The structured request is inside the exact supported math boundary and does not ask for language generation.",
            "ai": "The request needs an explanation or language generation, or is a bounded natural-language prompt.",
            "refuse": "The request is unsafe, malformed, or outside the allowed input size.",
        },
    }


def _decision_payload(*, payload: dict[str, Any] | None, prompt: str | None, config: JevConfig) -> dict[str, Any]:
    state: dict[str, Any] = {"mode": "route"}
    if payload is not None:
        state["structured_request"] = payload
    if prompt is not None:
        state["prompt"] = prompt
    return {"model": config.model, "state": state, "questions": {"route": _route_question()}}


def deterministic_choice(*, payload: dict[str, Any] | None, prompt: str | None) -> tuple[str, str]:
    """Return the safe no-model route for a validated request."""
    if payload is not None:
        return "solver", "validated structured request uses the exact solver"
    if prompt is not None:
        return "ai", "plain-language prompt requires a language model"
    return "refuse", "a structured request or prompt is required"


def _base_metadata(*, started: float, source: str, choice: str, reason: str) -> dict[str, Any]:
    return {
        "source": source,
        "choice": choice,
        "reason": reason,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "attempts": [],
        "jev_calls": 0,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "model": None,
    }


def _parse_choice(body: Any) -> tuple[str, dict[str, int | None]]:
    if not isinstance(body, dict):
        raise RouterError("The routing response was not an object.")
    answers = body.get("answers")
    route = answers.get("route") if isinstance(answers, dict) else None
    if not isinstance(route, dict) or route.get("type") != "choice":
        raise RouterError("The routing response did not contain a choice.")
    choice = route.get("choice")
    if choice not in ROUTE_CHOICES:
        raise RouterError("The routing response contained an unsupported choice.")
    confidence = route.get("confidence")
    if confidence is not None:
        if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                or not math.isfinite(float(confidence)) or not 0 <= float(confidence) <= 1):
            raise RouterError("The routing response contained an invalid confidence.")
    probabilities = route.get("probabilities")
    if probabilities is not None:
        if not isinstance(probabilities, dict):
            raise RouterError("The routing probabilities were malformed.")
        for key, value in probabilities.items():
            if (key not in ROUTE_CHOICES or isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value)) or not 0 <= float(value) <= 1):
                raise RouterError("The routing probabilities were malformed.")
    return choice, _usage(body)


async def _jev_call(app: Any, *, payload: dict[str, Any] | None,
                    prompt: str | None, config: JevConfig) -> tuple[str, dict[str, Any]]:
    acquired = await asyncio.to_thread(_JEV_CONCURRENCY.acquire, False)
    if not acquired:
        raise RouterError("The Jev router is busy.")
    attempted_at = time.perf_counter()
    transport = getattr(app.state, "jev_transport", None)
    headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}
    request_body = _decision_payload(payload=payload, prompt=prompt, config=config)

    async def send() -> httpx.Response:
        async with httpx.AsyncClient(transport=transport, timeout=config.timeout_seconds) as client:
            return await client.post(config.base_url, headers=headers, json=request_body)

    try:
        response = await asyncio.wait_for(send(), timeout=config.timeout_seconds)
    except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
        raise RouterError("The Jev router did not respond before the deadline.") from exc
    except httpx.RequestError as exc:
        raise RouterError("The Jev router could not be reached.") from exc
    finally:
        _JEV_CONCURRENCY.release()

    try:
        body = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RouterError("The Jev router returned malformed JSON.") from exc
    if response.status_code < 200 or response.status_code >= 300:
        raise RouterError("The Jev router returned an error.")
    choice, parsed_usage = _parse_choice(body)
    metadata = {
        "provider": "jev",
        "model": body.get("model") if isinstance(body, dict) and isinstance(body.get("model"), str) else config.model,
        "elapsed_ms": round((time.perf_counter() - attempted_at) * 1000, 3),
        "ai_calls": 1,
        **parsed_usage,
    }
    return choice, metadata


async def choose_route(app: Any, *, mode: Literal["deterministic", "jev", "ai_only"],
                       payload: dict[str, Any] | None, prompt: str | None) -> dict[str, Any]:
    started = time.perf_counter()
    if prompt is not None and len(prompt) > _MAX_PROMPT_LENGTH:
        return _base_metadata(started=started, source="validation", choice="refuse",
                              reason="prompt exceeds the bounded length")
    fallback_choice, fallback_reason = deterministic_choice(payload=payload, prompt=prompt)
    if mode == "deterministic":
        return _base_metadata(started=started, source="deterministic", choice=fallback_choice,
                              reason=fallback_reason)
    if mode == "ai_only":
        return _base_metadata(started=started, source="ai_only", choice="ai",
                              reason="AI-only comparison route")

    metadata = _base_metadata(started=started, source="deterministic_fallback",
                              choice=fallback_choice, reason=fallback_reason)
    config = _jev_config()
    if config is None:
        metadata["reason"] = "Jev is not configured; deterministic fallback selected"
        metadata["attempts"].append({"provider": "jev", "status": "missing_config", "ai_calls": 0})
        return metadata
    try:
        choice, attempt = await _jev_call(app, payload=payload, prompt=prompt, config=config)
    except RouterError as exc:
        metadata["reason"] = f"Jev failed; {fallback_reason}"
        metadata["attempts"].append({"provider": "jev", "status": "failed", "detail": str(exc),
                                      "ai_calls": 1, "input_tokens": None,
                                      "output_tokens": None, "total_tokens": None})
        metadata["jev_calls"] = 1
        metadata["model"] = config.model
        return metadata
    metadata.update({"source": "jev", "choice": choice, "reason": "Jev typed route decision",
                     "model": attempt.get("model"), "jev_calls": 1,
                     "input_tokens": attempt.get("input_tokens"),
                     "output_tokens": attempt.get("output_tokens"),
                     "total_tokens": attempt.get("total_tokens")})
    metadata["attempts"].append({"provider": "jev", "status": "ok", **attempt})
    return metadata
