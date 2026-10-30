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


def test_health_reports_local_ollama_configuration_without_a_key(monkeypatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:4b")
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "ai_configured": True}


def test_derivative_uses_exact_route_and_independent_numeric_evidence() -> None:
    response = client.post("/api/solve", json={"operation": "derivative", "expression": "x^3"})
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "solved"
    assert body["result"] == "3*x**2"
    assert body["verification"]["status"] == "numerical_evidence"
    assert body["metrics"]["ai_calls"] == 0
    assert body["metrics"]["solver_ms"] is not None
    assert body["steps"]
    assert any("derivative" in step.lower() for step in body["steps"])
    assert any("power rule" in step.lower() for step in body["steps"])


def test_solution_steps_name_the_integral_rule_family() -> None:
    response = client.post("/api/solve", json={"operation": "integral", "expression": "2*x + cos(x)"})
    body = response.json()
    assert response.status_code == 200
    assert any("linearity" in step.lower() for step in body["steps"])
    assert any("integrate 2*x" in step.lower() and "integrate cos(x)" in step.lower() for step in body["steps"])


def test_integration_by_parts_shows_the_remaining_integral() -> None:
    response = client.post('/api/solve', json={'operation': 'integral', 'expression': 'x*exp(x)'})
    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'solved'
    steps = '\n'.join(body['steps'])
    assert 'Integration by parts' in steps
    assert 'u = x; du/dx = 1' in steps
    assert 'v = exp(x)' in steps
    assert 'integral v*du' in steps
    assert 'Remaining integral: integral exp(x) dx = exp(x)' in steps
    assert body['verification']['status'] == 'symbolic_check'
    assert body['metrics']['ai_calls'] == 0


def test_linear_argument_integrals_show_substitution_and_scale() -> None:
    for expression, expected, substitution, slope in (
        ("sin(2*x+1)", "-cos(2*x + 1)/2", "2*x + 1", "2"),
        ("cos(3*x)", "sin(3*x)/3", "3*x", "3"),
        ("exp(-2*x)", "-exp(-2*x)/2", "-2*x", "-2"),
    ):
        response = client.post("/api/solve", json={"operation": "integral", "expression": expression})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "solved"
        assert body["result"] == expected
        assert any(f"u = {substitution}" in step and f"du = ({slope})*dx" in step and expected in step for step in body["steps"])
        assert body["verification"]["status"] == "symbolic_check"
        assert body["metrics"]["ai_calls"] == 0


def test_integration_by_parts_preserves_trig_scaling_and_negative_slopes() -> None:
    for expression, choice, primitive, remaining in (
        ('3*x*cos(2*x+1)', 'u = 3*x; du/dx = 3', 'v = sin(2*x + 1)/2', 'integral 3*sin(2*x + 1)/2 dx = -3*cos(2*x + 1)/4'),
        ('x*sin(x)', 'u = x; du/dx = 1', 'v = -cos(x)', 'integral -cos(x) dx = -sin(x)'),
        ('(x+1)*exp(-2*x)', 'u = x + 1; du/dx = 1', 'v = -exp(-2*x)/2', 'integral -exp(-2*x)/2 dx = exp(-2*x)/4'),
    ):
        response = client.post('/api/solve', json={'operation': 'integral', 'expression': expression})
        assert response.status_code == 200
        body = response.json()
        assert body['status'] == 'solved'
        steps = '\n'.join(body['steps'])
        assert choice in steps
        assert primitive in steps
        assert remaining in steps
        assert body['steps'][-1].startswith('Verification')
        assert len(body['steps']) <= 8
        assert all(len(step) <= 500 for step in body['steps'])
        assert body['verification']['status'] == 'symbolic_check'
        assert body['metrics']['ai_calls'] == 0


def test_nonlinear_inner_integral_does_not_claim_linear_parts_shortcut() -> None:
    response = client.post('/api/solve', json={'operation': 'integral', 'expression': 'x*exp(x^2)'})
    body = response.json()
    assert response.status_code == 200
    assert body['status'] == 'solved'
    assert body['result'] == 'exp(x**2)/2'
    assert not any('Integration by parts:' in step for step in body['steps'])
    steps = '\n'.join(body['steps'])
    assert 'Use substitution u = x**2; du/dx = 2*x' in steps
    assert 'x = (1/2)*(du/dx)' in steps
    assert 'integral exp(u)/2 du = exp(u)/2' in steps


def test_integrals_show_constant_and_power_rule_arithmetic() -> None:
    for expression, expected, step_fragment in (
        ("x^3", "x**4/4", "n = 3"),
        ("x", "x**2/2", "n = 1"),
        ("1/x^2", "-1/x", "n = -2"),
        ("1/x", "log(Abs(x))", "n = -1"),
        ("5", "5*x", "constant"),
        ("3*sin(2*x)", "-3*cos(2*x)/2", "u = 2*x"),
    ):
        response = client.post("/api/solve", json={"operation": "integral", "expression": expression})
        body = response.json()
        assert response.status_code == 200
        assert body["status"] == "solved"
        assert body["result"] == expected
        assert any(step_fragment in step for step in body["steps"])
        if expression == "3*sin(2*x)":
            assert any("constant factor 3" in step and "u = 2*x" in step for step in body["steps"])
        assert body["metrics"]["ai_calls"] == 0


def test_nonlinear_substitution_steps_show_trig_scaling_and_the_complete_differential() -> None:
    for expression, expected, substitution, differential, rewritten in (
        ('2*x*cos(x^2+1)', 'sin(x**2 + 1)', 'x**2 + 1', '2*x', 'integral cos(u) du = sin(u)'),
        ('-6*x*sin(3*x^2+2)', 'cos(3*x**2 + 2)', '3*x**2 + 2', '6*x', 'integral -sin(u) du = cos(u)'),
        ('(3*x^2+2)*exp(x^3+2*x)', 'exp(x**3 + 2*x)', 'x**3 + 2*x', '3*x**2 + 2', 'integral exp(u) du = exp(u)'),
    ):
        response = client.post('/api/solve', json={'operation': 'integral', 'expression': expression})
        assert response.status_code == 200
        body = response.json()
        assert body['status'] == 'solved'
        assert body['result'] == expected
        steps = '\n'.join(body['steps'])
        assert f'Use substitution u = {substitution}; du/dx = {differential}' in steps
        assert rewritten in steps
        assert f'Substitute u = {substitution} back to get {expected}' in steps
        assert body['verification']['status'] == 'symbolic_check'
        assert body['metrics']['ai_calls'] == 0
        assert len(body['steps']) <= 8
        assert all(len(step) <= 500 for step in body['steps'])


def test_substitution_does_not_match_only_the_leading_coefficient() -> None:
    response = client.post('/api/solve', json={'operation': 'integral', 'expression': '(2*x+1)*exp(x^2)'})
    body = response.json()
    assert response.status_code == 200
    assert body['status'] == 'solved'
    assert not any('Match the differential:' in step for step in body['steps'])
    assert body['metrics']['ai_calls'] == 0


def test_product_derivative_step_shows_the_intermediate_rule() -> None:
    response = client.post("/api/solve", json={"operation": "derivative", "expression": "x^3*sin(x)"})
    body = response.json()
    assert response.status_code == 200
    assert any("product rule:" in step.lower() and "sin(x)" in step for step in body["steps"])
    assert all("\ufffd" not in step for step in body["steps"])


def test_composite_derivatives_show_inner_and_outer_chain_factors() -> None:
    for expression, expected, inner, inner_derivative in (
        ("sin(x^2)", "2*x*cos(x**2)", "x**2", "2*x"),
        ("log(3*x+1)", "3/(3*x + 1)", "3*x + 1", "3"),
        ("exp(-2*x)", "-2*exp(-2*x)", "-2*x", "-2"),
    ):
        response = client.post("/api/solve", json={"operation": "derivative", "expression": expression})
        body = response.json()
        assert response.status_code == 200
        assert body["status"] == "solved"
        assert body["result"] == expected
        assert any("Chain rule:" in step and f"u = {inner}" in step and f"du/dx = {inner_derivative}" in step and expected in step for step in body["steps"])
        assert body["verification"]["status"] == "numerical_evidence"
        assert body["metrics"]["ai_calls"] == 0


def test_each_supported_operation_returns_bounded_deterministic_steps() -> None:
    requests = [
        {"operation": "derivative", "expression": "x^3"},
        {"operation": "integral", "expression": "x", "lower": "0", "upper": "1"},
        {"operation": "limit", "expression": "sin(x)/x", "target": "0", "direction": "both"},
        {"operation": "equation", "expression": "x^2 = 1"},
    ]
    for request in requests:
        response = client.post("/api/solve", json=request)
        body = response.json()
        assert response.status_code == 200
        assert body["status"] == "solved"
        assert isinstance(body["steps"], list)
        assert 1 <= len(body["steps"]) <= 8
        assert all(isinstance(step, str) and step and len(step) <= 500 for step in body["steps"])


def test_unresolved_response_explains_where_exact_route_stopped() -> None:
    response = client.post("/api/solve", json={"operation": "limit", "expression": "1/x", "target": "0", "direction": "both"})
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "unresolved"
    assert body["steps"][-1].startswith("Stop before returning an exact answer:")


def test_derivative_verification_does_not_sample_outside_raw_domain() -> None:
    response = client.post("/api/solve", json={"operation": "derivative", "expression": "sqrt(x-10)^2"})
    body = response.json()
    assert response.status_code == 200
    assert body["result"] == "1"
    assert body["verification"]["status"] == "not_checked"
    assert "branch points" in body["notes"][0]


def test_derivative_domain_note_calls_out_denominator_holes() -> None:
    response = client.post("/api/solve", json={"operation": "derivative", "expression": "1/x"})
    body = response.json()
    assert response.status_code == 200
    assert "denominator holes" in body["notes"][0]


def test_indefinite_integral_is_checked_by_differentiating_antiderivative() -> None:
    response = client.post("/api/solve", json={"operation": "integral", "expression": "2*x"})
    body = response.json()
    assert response.status_code == 200
    assert body["result"] == "x**2"
    assert body["verification"]["status"] == "symbolic_check"


def test_real_logarithmic_antiderivative_uses_abs_and_states_domain() -> None:
    response = client.post("/api/solve", json={"operation": "integral", "expression": "1/x"})
    body = response.json()
    assert response.status_code == 200
    assert body["result"] == "log(Abs(x))"
    assert body["verification"]["status"] == "numerical_evidence"
    assert "sample points" in body["verification"]["detail"]
    assert "nonzero" in body["notes"][1]


def test_logarithmic_branch_accepts_a_symbolic_residual_check() -> None:
    verification = solver._verify_branch_antiderivative(solver.sp.Integer(0), solver.sp.log(solver.sp.Integer(2)))
    assert verification["status"] == "symbolic_check"


def test_integral_linearity_steps_preserve_the_real_logarithmic_branch() -> None:
    for expression in ("x + 1/x", "x + 1/(x-1)"):
        response = client.post("/api/solve", json={"operation": "integral", "expression": expression})
        body = response.json()
        assert response.status_code == 200
        assert body["status"] == "solved"
        assert "log(Abs(" in body["result"]
        assert any("linearity" in step and "log(Abs(" in step for step in body["steps"])
        assert any("original integrand" in note for note in body["notes"])
        assert body["metrics"]["ai_calls"] == 0


def test_definite_integral_reports_independent_quadrature() -> None:
    response = client.post("/api/solve", json={"operation": "integral", "expression": "x", "lower": "0", "upper": "1"})
    body = response.json()
    assert response.status_code == 200
    assert body["result"] == "1/2"
    assert body["verification"]["status"] == "numerical_evidence"


def test_polynomial_definite_integrals_show_antiderivative_and_bound_values() -> None:
    for expression, lower, upper, result, primitive, upper_value, lower_value in (
        ("x^2", "0", "1", "1/3", "x**3/3", "1/3", "0"),
        ("3*x+2", "-1", "2", "21/2", "3*x**2/2 + 2*x", "10", "-1/2"),
        ("5", "0", "2", "10", "5*x", "10", "0"),
    ):
        response = client.post("/api/solve", json={"operation": "integral", "expression": expression, "lower": lower, "upper": upper})
        body = response.json()
        assert response.status_code == 200
        assert body["status"] == "solved"
        assert body["result"] == result
        assert any(f"F(x) = {primitive}" in step for step in body["steps"])
        assert any(f"F({upper}) = {upper_value}" in step and f"F({lower}) = {lower_value}" in step for step in body["steps"])
        assert any("F(b) - F(a)" in step and result in step for step in body["steps"])
        assert body["verification"]["status"] == "numerical_evidence"
        assert body["metrics"]["ai_calls"] == 0


def test_improper_integrals_accept_infinite_bounds_with_honest_check_status() -> None:
    for expression, lower, upper in [("exp(x)", "-oo", "0"), ("exp(-x)", "0", "oo")]:
        response = client.post("/api/solve", json={"operation": "integral", "expression": expression, "lower": lower, "upper": upper})
        body = response.json()
        assert response.status_code == 200
        assert body["status"] == "solved"
        assert body["result"] == "1"
        assert body["verification"]["status"] == "not_checked"


def test_limit_requires_an_explicit_direction() -> None:
    response = client.post("/api/solve", json={"operation": "limit", "expression": "sin(x)/x", "target": "0"})
    assert response.status_code == 422
    assert "direction" in response.json()["detail"].lower()

    response = client.post("/api/solve", json={"operation": "limit", "expression": "sin(x)/x", "target": "0", "direction": "both"})
    body = response.json()
    assert response.status_code == 200
    assert body["result"] == "1"
    assert body["verification"]["status"] == "numerical_evidence"
    assert any("real domain" in step for step in body["steps"])
    assert any("left-hand limit = 1" in step.lower() and "right-hand limit = 1" in step.lower() for step in body["steps"])


def test_equation_returns_real_roots_and_checks_substitution() -> None:
    response = client.post("/api/solve", json={"operation": "equation", "expression": "x-2=0"})
    body = response.json()
    assert response.status_code == 200
    assert body["result"] == "{2}"
    assert body["verification"]["status"] == "symbolic_check"


def test_equation_distinguishes_tiny_complex_roots_from_tiny_real_roots() -> None:
    for expression, expected in (
        ('x^2+1e-24=0', '{}'),
        ('x^2-1e-24=0', '{-1/1000000000000, 1/1000000000000}'),
    ):
        response = client.post('/api/solve', json={'operation': 'equation', 'expression': expression})
        assert response.status_code == 200
        body = response.json()
        assert body['status'] == 'solved', body
        assert body['result'] == expected
        assert body['metrics']['ai_calls'] == 0


def test_scaled_cubic_does_not_mistake_nearby_complex_roots_for_real_roots() -> None:
    response = client.post('/api/solve', json={'operation': 'equation', 'expression': 'x^3+1e-24*x+1e-36=0'})
    body = response.json()
    assert response.status_code == 200
    assert body['status'] == 'solved', body
    # Multiplying by 10^36 gives this integer polynomial. Its derivative is
    # positive everywhere, so it has exactly one real root.
    assert body['result'] == '{CRootOf(1000000000000000000000000000000000000*x**3 + 1000000000000*x + 1, 0)}'
    assert body['verification']['status'] == 'symbolic_check'
    assert body['metrics']['ai_calls'] == 0


def test_exact_root_isolation_keeps_all_real_roots_of_irreducible_polynomials() -> None:
    for expression, polynomial, indices in (
        ('x^3-3*x+1=0', 'x**3 - 3*x + 1', (0, 1, 2)),
        ('x^4-x-1=0', 'x**4 - x - 1', (0, 1)),
    ):
        response = client.post('/api/solve', json={'operation': 'equation', 'expression': expression})
        body = response.json()
        assert response.status_code == 200
        assert body['status'] == 'solved'
        expected = '{' + ', '.join(f'CRootOf({polynomial}, {index})' for index in indices) + '}'
        assert body['result'] == expected
        assert body['verification']['status'] == 'symbolic_check'
        assert any('not a rounded approximation' in note for note in body['notes'])
        assert body['metrics']['ai_calls'] == 0


def test_exact_root_isolation_does_not_invent_real_roots_of_a_positive_quartic() -> None:
    # Its minimum occurs at x = 4^(-1/3), where x^4-x+1 = 1-3*x/4 > 0.
    response = client.post('/api/solve', json={'operation': 'equation', 'expression': 'x^4-x+1=0'})
    body = response.json()
    assert response.status_code == 200
    assert body['status'] == 'solved'
    assert body['result'] == '{}'
    assert body['verification']['status'] == 'not_checked'


def test_nonrational_polynomial_coefficients_keep_exact_real_classification() -> None:
    for expression, expected in (
        ('x^2-pi=0', '{-sqrt(pi), sqrt(pi)}'),
        ('x^2+pi=0', '{}'),
    ):
        response = client.post('/api/solve', json={'operation': 'equation', 'expression': expression})
        body = response.json()
        assert response.status_code == 200
        assert body['status'] == 'solved'
        assert body['result'] == expected
        assert body['metrics']['ai_calls'] == 0


def test_equation_allows_whitespace_around_equals() -> None:
    response = client.post("/api/solve", json={"operation": "equation", "expression": "x^2 = 1"})
    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "{-1, 1}"
    assert any("factor the polynomial" in step.lower() for step in body["steps"])


def test_quadratic_steps_show_coefficients_discriminant_and_root_rule() -> None:
    for expression, expected, coefficients, discriminant in (
        ("x^2-5*x+6=0", "{2, 3}", "a = 1, b = -5, c = 6", "1"),
        ("x^2-2=0", "{-sqrt(2), sqrt(2)}", "a = 1, b = 0, c = -2", "8"),
        ("x^2-2*x+1=0", "{1}", "a = 1, b = -2, c = 1", "0"),
        ("2*x^2-8=0", "{-2, 2}", "a = 2, b = 0, c = -8", "64"),
        ("x^2+1=0", "{}", "a = 1, b = 0, c = 1", "-4"),
    ):
        response = client.post("/api/solve", json={"operation": "equation", "expression": expression})
        body = response.json()
        assert response.status_code == 200
        assert body["status"] == "solved"
        assert body["result"] == expected
        assert any(coefficients in step and f"D = b^2 - 4*a*c = {discriminant}" in step for step in body["steps"])
        if discriminant == "-4":
            assert any("negative" in step and "no real roots" in step for step in body["steps"])
        else:
            assert any("x = (-b +/- sqrt(D))/(2*a)" in step for step in body["steps"])
        assert 1 <= len(body["steps"]) <= 8
        assert body["steps"][-1].startswith("Verification")


def test_empty_real_solution_set_does_not_claim_a_substitution_check() -> None:
    for expression in ("x^2 + 1 = 0", "x^4 + 1 = 0"):
        response = client.post("/api/solve", json={"operation": "equation", "expression": expression})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "solved"
        assert body["result"] == "{}"
        assert body["verification"]["status"] == "not_checked"
        assert "does not independently prove" in body["verification"]["detail"]
        assert any("empty real solution set" in step for step in body["steps"])
        assert not any(step.startswith("Substitute the returned roots") for step in body["steps"])
        assert body["metrics"]["ai_calls"] == 0


def test_equation_accepts_a_bounded_nested_quartic() -> None:
    response = client.post("/api/solve", json={"operation": "equation", "expression": "(x^2-1)^2=0"})
    assert response.status_code == 200
    assert response.json()["result"] == "{-1, 1}"


def test_cancelled_nonpolynomial_equation_does_not_claim_all_real_x() -> None:
    response = client.post("/api/solve", json={"operation": "equation", "expression": "log(x)=log(x)"})
    assert response.status_code == 200
    assert response.json()["status"] == "unresolved"


def test_equation_identity_and_constant_cases_skip_factorization_claims() -> None:
    for expression in ("x=x", "1=2"):
        response = client.post("/api/solve", json={"operation": "equation", "expression": expression})
        body = response.json()
        assert response.status_code == 200
        assert body["status"] == "solved"
        assert not any("factor the polynomial" in step.lower() for step in body["steps"])


def test_real_constant_function_coefficients_remain_polynomial() -> None:
    response = client.post("/api/solve", json={"operation": "equation", "expression": "sqrt(2)*x=1"})
    assert response.status_code == 200
    assert response.json()["result"] == "{sqrt(2)/2}"


def test_complex_constant_function_values_are_rejected() -> None:
    response = client.post("/api/solve", json={"operation": "derivative", "expression": "sqrt(-1)*x"})
    assert response.status_code == 422


def test_decimal_literals_are_exact_before_symbolic_cancellation() -> None:
    response = client.post(
        "/api/solve",
        json={"operation": "derivative", "expression": "(0.100000000000000001 - 0.1)*x"},
    )
    assert response.status_code == 200
    assert response.json()["result"] == "1/1000000000000000000"


def test_oversized_scientific_exponent_is_rejected() -> None:
    response = client.post("/api/solve", json={"operation": "derivative", "expression": "1e-999*x"})
    assert response.status_code == 422


def test_ordinary_decimal_literal_remains_supported() -> None:
    response = client.post("/api/solve", json={"operation": "derivative", "expression": "0.125*x"})
    assert response.status_code == 200
    assert response.json()["result"] == "1/8"


def test_nonexistent_two_sided_limit_is_explicit() -> None:
    response = client.post("/api/solve", json={"operation": "limit", "expression": "1/x", "target": "0", "direction": "both"})
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "unresolved"
    assert body["result"] is None
    assert body["verification"]["status"] == "not_checked"
    assert "left-hand limit" in body["notes"][0]
    assert "-oo" in body["notes"][0] and "oo" in body["notes"][0]


def test_limit_verification_does_not_sample_outside_raw_domain() -> None:
    response = client.post(
        "/api/solve",
        json={"operation": "limit", "expression": "sqrt(x-10)^2", "target": "0", "direction": "both"},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "unresolved"
    assert body["result"] is None
    assert body["verification"]["status"] == "not_checked"


def test_limit_requires_real_domain_points_in_the_requested_direction() -> None:
    for expression, target, direction in [
        ("sqrt(x)^2", "0", "-"),
        ("sqrt(x)^2", "0", "both"),
        ("sqrt(-x^2)", "0", "+"),
        ("sqrt(x)*sqrt(-x)", "0", "+"),
    ]:
        body = client.post("/api/solve", json={"operation": "limit", "expression": expression,
            "target": target, "direction": direction}).json()
        assert body["status"] == "unresolved", (expression, body)
        assert body["result"] is None


def test_one_sided_limit_steps_show_the_evaluated_side() -> None:
    response = client.post("/api/solve", json={"operation": "limit", "expression": "sqrt(x)", "target": "0", "direction": "+"})
    body = response.json()
    assert response.status_code == 200
    assert body["verification"]["status"] == "numerical_evidence"
    assert any("one-sided limit evaluates to 0" in step.lower() for step in body["steps"])


def test_limit_retains_valid_endpoints_holes_and_unbounded_real_domains() -> None:
    for expression, target, direction, expected in [
        ("sqrt(x)^2", "0", "+", "0"),
        ("sqrt(x-10)^2", "10", "+", "0"),
        ("x/x", "0", "both", "1"),
        ("sqrt(x)^2", "oo", "both", "oo"),
        ("x^2", "-oo", "both", "oo"),
    ]:
        body = client.post("/api/solve", json={"operation": "limit", "expression": expression,
            "target": target, "direction": direction}).json()
        assert body["status"] == "solved", (expression, body)
        assert body["result"] == expected
        if target not in {"oo", "-oo"}:
            assert body["verification"]["status"] == "numerical_evidence", (expression, body)


def test_limit_rejects_infinite_target_outside_the_raw_domain() -> None:
    response = client.post(
        "/api/solve",
        json={"operation": "limit", "expression": "sqrt(x)^2", "target": "-oo", "direction": "both"},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "unresolved"
    assert body["result"] is None


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


def test_definite_integral_rejects_an_unsimplified_domain_gap() -> None:
    response = client.post(
        "/api/solve",
        json={
            "operation": "integral",
            "expression": "sqrt((x-1)*(x-2))^2",
            "lower": "0",
            "upper": "5",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "unresolved"


def test_endpoint_improper_integral_can_still_be_solved() -> None:
    response = client.post(
        "/api/solve",
        json={"operation": "integral", "expression": "1/sqrt(x)", "lower": "0", "upper": "1"},
    )
    assert response.status_code == 200
    assert response.json()["result"] == "2"


def test_definite_integral_preserves_a_cancelled_denominator_hole() -> None:
    response = client.post("/api/solve", json={"operation": "integral", "expression": "x/x", "lower": "-1", "upper": "1"})
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "unresolved"


def test_definite_integral_checks_periodic_cancelled_denominator_zeros() -> None:
    response = client.post(
        "/api/solve",
        json={
            "operation": "integral",
            "expression": "sin(x)/sin(x)",
            "lower": "2*pi",
            "upper": "4*pi",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "unresolved"


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
    assert 'id="session-download"' in response.text
    assert "Ctrl+K or Cmd+K" in response.text
