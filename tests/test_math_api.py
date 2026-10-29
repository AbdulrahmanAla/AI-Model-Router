"""Public API checks for the bounded exact route."""

from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from app.main import app
from app import solver


client = TestClient(app)


def test_health_does_not_expose_provider_secrets() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "ai_configured": False}


def test_derivative_uses_exact_route_and_independent_numeric_evidence() -> None:
    response = client.post("/api/solve", json={"operation": "derivative", "expression": "x^3"})
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "solved"
    assert body["result"] == "3*x**2"
    assert body["verification"]["status"] == "numerical_evidence"
    assert body["metrics"]["ai_calls"] == 0
    assert body["metrics"]["solver_ms"] is not None


def test_indefinite_integral_is_checked_by_differentiating_antiderivative() -> None:
    response = client.post("/api/solve", json={"operation": "integral", "expression": "2*x"})
    body = response.json()
    assert response.status_code == 200
    assert body["result"] == "x**2"
    assert body["verification"]["status"] == "symbolic_check"


def test_definite_integral_reports_independent_quadrature() -> None:
    response = client.post("/api/solve", json={"operation": "integral", "expression": "x", "lower": "0", "upper": "1"})
    body = response.json()
    assert response.status_code == 200
    assert body["result"] == "1/2"
    assert body["verification"]["status"] == "numerical_evidence"


def test_limit_uses_both_sides_when_direction_is_omitted() -> None:
    response = client.post("/api/solve", json={"operation": "limit", "expression": "sin(x)/x", "target": "0"})
    body = response.json()
    assert response.status_code == 200
    assert body["result"] == "1"
    assert body["verification"]["status"] == "numerical_evidence"


def test_equation_returns_real_roots_and_checks_substitution() -> None:
    response = client.post("/api/solve", json={"operation": "equation", "expression": "x-2=0"})
    body = response.json()
    assert response.status_code == 200
    assert body["result"] == "{2}"
    assert body["verification"]["status"] == "symbolic_check"


def test_nonexistent_two_sided_limit_is_explicit() -> None:
    response = client.post("/api/solve", json={"operation": "limit", "expression": "1/x", "target": "0"})
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "unresolved"
    assert body["result"] is None
    assert body["verification"]["status"] == "not_checked"
    assert "left-hand limit" in body["notes"][0]
    assert "-oo" in body["notes"][0] and "oo" in body["notes"][0]


def test_rejects_unsafe_python_and_implicit_multiplication() -> None:
    for expression in ("__import__('os')", "2x", "x.__class__", "sin(x, 2)"):
        response = client.post("/api/solve", json={"operation": "derivative", "expression": expression})
        assert response.status_code == 422, expression
        assert response.json()["metrics"]["route"] == "validation"
        assert response.json()["metrics"]["ai_calls"] == 0


def test_rejects_exponent_towers_before_solver_work() -> None:
    for expression in ("9**9**9", "x**(9**9)", "((x+1)**20)**20"):
        response = client.post("/api/solve", json={"operation": "derivative", "expression": expression})
        assert response.status_code == 422, expression


def test_rejects_equation_with_variable_denominator() -> None:
    response = client.post("/api/solve", json={"operation": "equation", "expression": "x/x=1"})
    assert response.status_code == 422


def test_rejects_interior_integral_singularity() -> None:
    response = client.post("/api/solve", json={"operation": "integral", "expression": "1/(x-1)", "lower": "0", "upper": "2"})
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "unresolved"
    assert body["verification"]["status"] == "not_checked"


def test_definite_integral_preserves_unsimplified_square_root_domain() -> None:
    response = client.post("/api/solve", json={"operation": "integral", "expression": "sqrt(x)^2", "lower": "-1", "upper": "1"})
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "unresolved"
    assert body["verification"]["status"] == "not_checked"


def test_definite_integral_preserves_a_cancelled_denominator_hole() -> None:
    response = client.post("/api/solve", json={"operation": "integral", "expression": "x/x", "lower": "-1", "upper": "1"})
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "unresolved"


def test_request_shape_errors_are_422() -> None:
    response = client.post("/api/solve", json={"operation": "integral", "expression": "x", "lower": "0"})
    assert response.status_code == 422


def test_chunked_request_body_limit_is_enforced_before_parser() -> None:
    chunks = [
        b'{"operation":"derivative","expression":"',
        b"x" * (16 * 1024),
        b'"}',
    ]
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        if chunks:
            body = chunks.pop(0)
            return {"type": "http.request", "body": body, "more_body": bool(chunks)}
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/solve",
        "raw_path": b"/api/solve",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    response_start = next(message for message in sent if message["type"] == "http.response.start")
    assert response_start["status"] == 413
    response_body = next(message for message in sent if message["type"] == "http.response.body")["body"]
    payload = json.loads(response_body)
    assert payload["metrics"]["route"] == "validation"
    assert payload["metrics"]["ai_calls"] == 0


def test_solver_busy_is_503(monkeypatch) -> None:
    monkeypatch.setattr(solver, "_CONCURRENCY", solver.threading.BoundedSemaphore(0))
    response = client.post("/api/solve", json={"operation": "derivative", "expression": "x"})
    assert response.status_code == 503


def test_solver_deadline_is_an_honest_unresolved_result(monkeypatch) -> None:
    monkeypatch.setattr(solver, "SOLVER_TIMEOUT_MS", 1)
    response = client.post("/api/solve", json={"operation": "derivative", "expression": "x^2"})
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "unresolved"
    assert body["verification"]["status"] == "not_checked"
    assert body["metrics"]["ai_calls"] == 0


def test_root_serves_the_chat_shell() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "AI Math Assistant" in response.text
