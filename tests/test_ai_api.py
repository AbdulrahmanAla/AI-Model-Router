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
    for name in (
        "AI_PROVIDER",
        "AI_BASE_URL",
        "AI_API_KEY",
        "AI_MODEL",
        "AI_TIMEOUT_SECONDS",
        "AI_MAX_TOKENS",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
    ):
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


def test_limit_without_direction_is_rejected_before_provider_call(monkeypatch) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response("unused")

    configure_provider(monkeypatch, handler)
    result = client.post(
        "/api/ai",
        json={"action": "baseline", "request": {"operation": "limit", "expression": "sin(x)/x", "target": "0"}},
    )

    assert result.status_code == 422
    assert "direction" in result.json()["detail"].lower()
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


def configure_ollama(monkeypatch, handler):
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:4b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    app.state.ai_transport = httpx.MockTransport(handler)


def test_ollama_explanation_uses_native_endpoint_without_auth_and_maps_usage(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "qwen3.5:4b",
                "message": {"role": "assistant", "content": "The power rule gives 2*x."},
                "done": True,
                "total_duration": 123456789,
                "load_duration": 1000000,
                "prompt_eval_count": 31,
                "prompt_eval_duration": 2000000,
                "eval_count": 12,
                "eval_duration": 3000000,
            },
        )

    configure_ollama(monkeypatch, handler)
    result = client.post(
        "/api/ai",
        json={"action": "explain", "request": {"operation": "derivative", "expression": "x^2"}},
    )

    assert result.status_code == 200
    body = result.json()
    assert body["metrics"]["ai_calls"] == 1
    assert body["metrics"]["input_tokens"] == 31
    assert body["metrics"]["output_tokens"] == 12
    assert body["metrics"]["total_tokens"] == 43
    assert body["metrics"]["prompt_eval_count"] == 31
    assert body["metrics"]["eval_count"] == 12
    assert body["metrics"]["total_duration_ns"] == 123456789
    assert body["metrics"]["load_duration_ns"] == 1000000
    assert body["metrics"]["prompt_eval_duration_ns"] == 2000000
    assert body["metrics"]["eval_duration_ns"] == 3000000
    assert seen["url"] == "http://127.0.0.1:11434/api/chat"
    assert seen["authorization"] is None
    assert seen["body"]["stream"] is False
    assert seen["body"]["model"] == "qwen3.5:4b"


def test_ollama_baseline_accepts_native_machine_readable_response(monkeypatch):
    configure_ollama(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": '{"status":"solved","result":"2*x"}'},
                "done": True,
                "prompt_eval_count": 5,
                "eval_count": 6,
            },
        ),
    )
    result = client.post(
        "/api/ai",
        json={"action": "baseline", "request": {"operation": "derivative", "expression": "x^2"}},
    )
    assert result.status_code == 200
    assert json.loads(result.json()["text"]) == {"status": "solved", "result": "2*x"}
    assert result.json()["metrics"]["total_tokens"] == 11


def test_ollama_missing_model_does_not_call_provider(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={})

    monkeypatch.setenv("AI_PROVIDER", "ollama")
    app.state.ai_transport = httpx.MockTransport(handler)
    result = client.post(
        "/api/ai",
        json={"action": "baseline", "request": {"operation": "derivative", "expression": "x^2"}},
    )
    assert result.status_code == 503
    assert result.json()["metrics"]["ai_calls"] == 0
    assert calls == []


def test_ollama_malformed_response_is_redacted_and_counts_attempt(monkeypatch):
    configure_ollama(monkeypatch, lambda request: httpx.Response(200, json={"message": {"role": "assistant"}}))
    result = client.post(
        "/api/ai",
        json={"action": "baseline", "request": {"operation": "derivative", "expression": "x^2"}},
    )
    assert result.status_code == 502
    assert result.json()["metrics"]["ai_calls"] == 1


def test_ollama_timeout_counts_attempt(monkeypatch):
    class SlowTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(1)
            return httpx.Response(200, json={"message": {"content": "late"}})

    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:4b")
    monkeypatch.setenv("AI_TIMEOUT_SECONDS", "0.1")
    app.state.ai_transport = SlowTransport()
    result = client.post(
        "/api/ai",
        json={"action": "baseline", "request": {"operation": "derivative", "expression": "x^2"}},
    )
    assert result.status_code == 504
    assert result.json()["metrics"]["ai_calls"] == 1
