"""Public /api/ai contract tests using a fake external HTTP transport."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_ai_configuration(monkeypatch):
    for name in ("AI_BASE_URL", "AI_API_KEY", "AI_MODEL", "AI_TIMEOUT_SECONDS", "AI_MAX_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    app.state.ai_transport = None
    yield
    app.state.ai_transport = None


def configure_provider(monkeypatch, handler):
    monkeypatch.setenv("AI_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("AI_API_KEY", "test-secret")
    monkeypatch.setenv("AI_MODEL", "test-model")
    app.state.ai_transport = httpx.MockTransport(handler)


def response(
    content: str,
    usage: dict | None = None,
    status_code: int = 200,
    finish_reason: str | None = None,
) -> httpx.Response:
    choice = {"message": {"content": content}}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    body = {"choices": [choice]}
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(status_code, json=body)


def test_missing_configuration_does_not_call_provider(monkeypatch) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response("unused")

    app.state.ai_transport = httpx.MockTransport(handler)
    result = client.post(
        "/api/ai",
        json={"action": "explain", "request": {"operation": "derivative", "expression": "x^2"}},
    )

    assert result.status_code == 503
    assert result.json()["metrics"]["ai_calls"] == 0
    assert calls == []


def test_explanation_is_grounded_and_reports_usage(monkeypatch) -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["authorization"]
        payload = json.loads(request.content)
        seen["messages"] = payload["messages"]
        return response("The power rule gives the displayed derivative.", {"prompt_tokens": 31, "completion_tokens": 12, "total_tokens": 43})

    configure_provider(monkeypatch, handler)
    result = client.post(
        "/api/ai",
        json={"action": "explain", "request": {"operation": "derivative", "expression": "x^2"}},
    )

    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "answered"
    assert body["verification"]["status"] == "not_checked"
    assert body["metrics"]["ai_calls"] == 1
    assert body["metrics"]["input_tokens"] == 31
    assert body["metrics"]["output_tokens"] == 12
    assert body["metrics"]["total_tokens"] == 43
    assert seen["url"] == "https://provider.example/v1/chat/completions"
    assert seen["authorization"] == "Bearer test-secret"
    assert "2*x" in json.dumps(seen["messages"])
    assert "test-secret" not in result.text


def test_baseline_requires_one_machine_readable_json_object(monkeypatch) -> None:
    configure_provider(monkeypatch, lambda request: response("Here is the answer: 2*x"))
    result = client.post(
        "/api/ai",
        json={"action": "baseline", "request": {"operation": "derivative", "expression": "x^2"}},
    )

    assert result.status_code == 502
    assert result.json()["metrics"]["ai_calls"] == 1
    assert "Here is the answer" not in result.text


def test_fallback_accepts_json_and_preserves_unknown_usage(monkeypatch) -> None:
    configure_provider(monkeypatch, lambda request: response(json.dumps({"status": "solved", "result": "2*x"})))
    result = client.post(
        "/api/ai",
        json={"action": "fallback", "request": {"operation": "derivative", "expression": "x^2"}},
    )

    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "answered"
    assert body["verification"]["status"] == "not_checked"
    assert body["metrics"]["ai_calls"] == 1
    assert body["metrics"]["input_tokens"] is None
    assert body["metrics"]["output_tokens"] is None
    assert body["metrics"]["total_tokens"] is None
    assert json.loads(body["text"]) == {"status": "solved", "result": "2*x"}


def test_provider_timeout_counts_attempt_and_redacts_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider secret timeout")

    configure_provider(monkeypatch, handler)
    result = client.post(
        "/api/ai",
        json={"action": "baseline", "request": {"operation": "derivative", "expression": "x^2"}},
    )

    assert result.status_code == 504
    assert result.json()["metrics"]["ai_calls"] == 1
    assert "provider secret timeout" not in result.text


def test_provider_error_redacts_body_and_counts_attempt(monkeypatch) -> None:
    configure_provider(monkeypatch, lambda request: httpx.Response(401, text="token=provider-secret"))
    result = client.post(
        "/api/ai",
        json={"action": "baseline", "request": {"operation": "derivative", "expression": "x^2"}},
    )

    assert result.status_code == 502
    assert result.json()["metrics"]["ai_calls"] == 1
    assert "provider-secret" not in result.text


def test_invalid_equation_is_rejected_before_provider_call(monkeypatch) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response(json.dumps({"status": "solved", "result": ["0"]}))

    configure_provider(monkeypatch, handler)
    result = client.post(
        "/api/ai",
        json={"action": "baseline", "request": {"operation": "equation", "expression": "x/(x-1)=0"}},
    )

    assert result.status_code == 422
    assert calls == []


def test_common_function_equation_reaches_ai_fallback(monkeypatch) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response(json.dumps({"status": "unresolved", "result": None}))

    configure_provider(monkeypatch, handler)
    result = client.post(
        "/api/ai",
        json={"action": "fallback", "request": {"operation": "equation", "expression": "sin(x)=0"}},
    )

    assert result.status_code == 200
    assert len(calls) == 1
    assert json.loads(result.json()["text"]) == {"status": "unresolved", "result": None}


def test_fallback_can_return_a_symbolic_solution_family(monkeypatch) -> None:
    configure_provider(monkeypatch, lambda request: response(json.dumps({"status": "solved", "result": "x = n*pi, n integer"})))
    result = client.post(
        "/api/ai",
        json={"action": "fallback", "request": {"operation": "equation", "expression": "sin(x)=0"}},
    )
    assert result.status_code == 200
    assert json.loads(result.json()["text"])["result"] == "x = n*pi, n integer"


def test_ai_accepts_spaced_equation(monkeypatch) -> None:
    configure_provider(monkeypatch, lambda request: response(json.dumps({"status": "solved", "result": ["-1", "1"]})))
    result = client.post(
        "/api/ai",
        json={
            "action": "baseline",
            "request": {"operation": "equation", "expression": "x^2 = 1"},
        },
    )
    assert result.status_code == 200
    assert json.loads(result.json()["text"])["result"] == ["-1", "1"]


def test_ai_accepts_definite_integral_bounds(monkeypatch) -> None:
    configure_provider(monkeypatch, lambda request: response(json.dumps({"status": "solved", "result": "1/2"})))
    result = client.post(
        "/api/ai",
        json={
            "action": "baseline",
            "request": {"operation": "integral", "expression": "x", "lower": "0", "upper": "1"},
        },
    )
    assert result.status_code == 200
    assert json.loads(result.json()["text"])["result"] == "1/2"


def test_explanation_declines_unresolved_request_without_provider_call(monkeypatch) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response("unused")

    configure_provider(monkeypatch, handler)
    result = client.post(
        "/api/ai",
        json={
            "action": "explain",
            "request": {"operation": "integral", "expression": "1/(x-1)", "lower": "0", "upper": "2"},
        },
    )

    assert result.status_code == 409
    assert result.json()["metrics"]["ai_calls"] == 0
    assert calls == []


def test_incomplete_provider_choice_is_rejected(monkeypatch) -> None:
    configure_provider(monkeypatch, lambda request: httpx.Response(200, json={"choices": []}))
    result = client.post(
        "/api/ai",
        json={"action": "explain", "request": {"operation": "derivative", "expression": "x^2"}},
    )

    assert result.status_code == 502
    assert result.json()["metrics"]["ai_calls"] == 1


def test_oversized_explanation_is_rejected_at_the_provider_boundary(monkeypatch) -> None:
    configure_provider(monkeypatch, lambda request: response("x" * 12001))
    result = client.post(
        "/api/ai",
        json={"action": "explain", "request": {"operation": "derivative", "expression": "x^2"}},
    )

    assert result.status_code == 502
    assert result.json()["metrics"]["ai_calls"] == 1


def test_truncated_provider_choice_is_rejected(monkeypatch) -> None:
    configure_provider(monkeypatch, lambda request: response('{"status":"solved"', finish_reason="length"))
    result = client.post(
        "/api/ai",
        json={"action": "baseline", "request": {"operation": "derivative", "expression": "x^2"}},
    )

    assert result.status_code == 502
    assert result.json()["metrics"]["ai_calls"] == 1


def test_grammar_validation_has_a_worker_deadline(monkeypatch) -> None:
    from app import ai

    configure_provider(monkeypatch, lambda request: response('{"status":"solved","result":"2*x"}'))
    monkeypatch.setattr(ai, "GRAMMAR_TIMEOUT_MS", 1)
    result = client.post(
        "/api/ai",
        json={"action": "baseline", "request": {"operation": "derivative", "expression": "x^2"}},
    )

    assert result.status_code == 422


def test_grammar_validation_busy_is_503_without_a_provider_call(monkeypatch) -> None:
    from app import ai

    configure_provider(monkeypatch, lambda request: response('{"status":"solved","result":"2*x"}'))
    monkeypatch.setattr(ai, "_GRAMMAR_CONCURRENCY", ai.threading.BoundedSemaphore(0))
    result = client.post(
        "/api/ai",
        json={"action": "baseline", "request": {"operation": "derivative", "expression": "x^2"}},
    )

    assert result.status_code == 503
    assert "busy" in result.json()["detail"]


def test_provider_has_an_outer_wall_clock_deadline(monkeypatch) -> None:
    class SlowTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(1)
            return response('{"status":"solved","result":"2*x"}')

    monkeypatch.setenv("AI_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("AI_API_KEY", "test-secret")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_TIMEOUT_SECONDS", "0.1")
    app.state.ai_transport = SlowTransport()
    result = client.post(
        "/api/ai",
        json={"action": "baseline", "request": {"operation": "derivative", "expression": "x^2"}},
    )

    assert result.status_code == 504
    assert result.json()["metrics"]["ai_calls"] == 1
