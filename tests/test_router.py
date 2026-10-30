"""Public /api/route contract tests with a fake Jev transport."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_router_configuration(monkeypatch):
    for name in ("TYPESAFE_API_KEY", "JEV_BASE_URL", "JEV_MODEL", "JEV_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    app.state.jev_transport = None
    yield
    app.state.jev_transport = None


def jev_response(choice: str = "solver", usage: dict | None = None) -> httpx.Response:
    body = {"model": "jev-1.14.0", "answers": {"route": {"type": "choice", "choice": choice}}}
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


def test_deterministic_route_solves_structured_math_without_model_call() -> None:
    result = client.post(
        "/api/route",
        json={"mode": "deterministic", "request": {"operation": "derivative", "expression": "x^2"}},
    )
    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "routed"
    assert body["answer"]["status"] == "solved"
    assert body["answer"]["result"] == "2*x"
    assert body["routing"]["source"] == "deterministic"
    assert body["routing"]["choice"] == "solver"


def test_jev_route_sends_typed_choice_request_and_preserves_usage(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return jev_response("solver", {"input_tokens": 12, "output_tokens": 4})

    monkeypatch.setenv("TYPESAFE_API_KEY", "jev-secret")
    monkeypatch.setenv("JEV_BASE_URL", "https://jev.example/v1/systemone")
    app.state.jev_transport = httpx.MockTransport(handler)
    result = client.post(
        "/api/route",
        json={"mode": "jev", "request": {"operation": "derivative", "expression": "x^2"}},
    )
    assert result.status_code == 200
    body = result.json()
    assert body["answer"]["result"] == "2*x"
    assert body["routing"]["source"] == "jev"
    assert body["routing"]["jev_calls"] == 1
    assert body["routing"]["total_tokens"] == 16
    assert seen["url"] == "https://jev.example/v1/systemone"
    assert seen["authorization"] == "Bearer jev-secret"
    payload = seen["body"]
    assert payload["model"] == "jev-latest"
    assert payload["questions"]["route"]["type"] == "choice"
    assert set(payload["questions"]["route"]["criteria"]) == {"solver", "ai", "refuse"}
    assert "jev-secret" not in result.text


def test_jev_missing_configuration_uses_deterministic_fallback() -> None:
    result = client.post(
        "/api/route",
        json={"mode": "jev", "request": {"operation": "limit", "expression": "sin(x)/x", "target": "0", "direction": "both"}},
    )
    assert result.status_code == 200
    body = result.json()
    assert body["answer"]["status"] == "solved"
    assert body["routing"]["source"] == "deterministic_fallback"
    assert body["routing"]["choice"] == "solver"
    assert body["routing"]["attempts"] == [{"provider": "jev", "status": "missing_config", "ai_calls": 0}]


def test_jev_malformed_response_falls_back_and_counts_attempt(monkeypatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "jev-secret")
    app.state.jev_transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"answers": {}}))
    result = client.post(
        "/api/route",
        json={"mode": "jev", "request": {"operation": "derivative", "expression": "x^2"}},
    )
    assert result.status_code == 200
    body = result.json()
    assert body["answer"]["result"] == "2*x"
    assert body["routing"]["source"] == "deterministic_fallback"
    assert body["routing"]["jev_calls"] == 1
    assert body["routing"]["attempts"][0]["status"] == "failed"
    assert body["routing"]["attempts"][0]["total_tokens"] is None
    assert "jev-secret" not in result.text


def test_route_requires_exactly_one_input() -> None:
    result = client.post("/api/route", json={"mode": "deterministic"})
    assert result.status_code == 422
    both = client.post(
        "/api/route",
        json={"mode": "deterministic", "prompt": "hi", "request": {"operation": "derivative", "expression": "x"}},
    )
    assert both.status_code == 422
