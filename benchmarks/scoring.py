"""Safe scoring and report helpers for the public benchmark route.

The scorer accepts only a small expression grammar. It never evaluates model
text as Python and it does not call the application solver to make expectations.
"""

from __future__ import annotations

import ast
import json
import math
from collections import Counter
from statistics import median
from typing import Any

import sympy as sp


_SYMBOLS = {"x": sp.Symbol("x"), "pi": sp.pi, "E": sp.E, "oo": sp.oo}
_FUNCTIONS = {
    "sin": sp.sin,
    "cos": sp.cos,
    "tan": sp.tan,
    "exp": sp.exp,
    "log": sp.log,
    "sqrt": sp.sqrt,
    "Abs": sp.Abs,
    "asin": sp.asin,
    "acos": sp.acos,
    "atan": sp.atan,
    "sinh": sp.sinh,
    "cosh": sp.cosh,
    "tanh": sp.tanh,
    "erf": sp.erf,
}
_BINARY_OPERATORS = {
    ast.Add: lambda left, right: left + right,
    ast.Sub: lambda left, right: left - right,
    ast.Mult: lambda left, right: left * right,
    ast.Div: lambda left, right: left / right,
    ast.Pow: lambda left, right: left**right,
}
_MAX_CONSTANT = 1_000_000_000_000
_MAX_EFFECTIVE_POWER = 10_000


class UnsafeResult(ValueError):
    """Raised when a response result is outside the benchmark grammar."""


def _numeric_tree_value(node: ast.AST) -> float:
    """Return a small numeric bound without constructing symbolic powers."""

    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        if isinstance(node.value, int) and abs(node.value) > _MAX_CONSTANT:
            raise UnsafeResult("numeric bound is too large")
        try:
            value = float(node.value)
        except OverflowError as exc:
            raise UnsafeResult("numeric bound is too large") from exc
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _numeric_tree_value(node.operand)
        if isinstance(node.op, ast.USub):
            value = -value
    elif isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _numeric_tree_value(node.left)
        right = _numeric_tree_value(node.right)
        try:
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            elif isinstance(node.op, ast.Mult):
                value = left * right
            elif isinstance(node.op, ast.Div):
                value = left / right
            else:
                value = left**right
        except (ArithmeticError, OverflowError):
            raise UnsafeResult("numeric bound is too large")
    else:
        raise UnsafeResult("power exponents must be numeric")
    if not math.isfinite(value) or abs(value) > 10000:
        raise UnsafeResult("numeric bound is too large")
    return value


def _effective_power_bound(node: ast.AST) -> float:
    if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow)):
        return 1.0
    exponent = abs(_numeric_tree_value(node.right))
    bound = _effective_power_bound(node.left) * exponent
    if bound > _MAX_EFFECTIVE_POWER:
        raise UnsafeResult("effective power is too large")
    return bound


def _validate_tree(node: ast.AST, depth: int = 0, count: list[int] | None = None) -> None:
    """Check AST size and power shape before creating SymPy objects."""

    count = count if count is not None else [0]
    count[0] += 1
    if count[0] > 80 or depth > 20:
        raise UnsafeResult("result expression is too large")
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
        _effective_power_bound(node)
    for child in ast.iter_child_nodes(node):
        _validate_tree(child, depth + 1, count)


def _expression_node(node: ast.AST) -> sp.Expr:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise UnsafeResult("only numeric constants are allowed")
        if isinstance(node.value, int) and abs(node.value) > _MAX_CONSTANT:
            raise UnsafeResult("numeric constant is too large")
        if isinstance(node.value, float) and not math.isfinite(node.value):
            raise UnsafeResult("non-finite constants are not allowed")
        return sp.Integer(node.value) if isinstance(node.value, int) else sp.Float(node.value)
    if isinstance(node, ast.Name) and node.id in _SYMBOLS:
        return _SYMBOLS[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _expression_node(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _expression_node(node.left)
        right = _expression_node(node.right)
        return _BINARY_OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS:
        if node.keywords or len(node.args) != 1:
            raise UnsafeResult("function arity is not allowed")
        return _FUNCTIONS[node.func.id](_expression_node(node.args[0]))
    raise UnsafeResult("result syntax is not allowed")


def parse_safe_expression(value: Any) -> sp.Expr:
    """Parse a bounded result expression without eval or an unrestricted parser."""

    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise UnsafeResult("result must be a short expression string")
    source = value.replace("^", "**")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise UnsafeResult("result is not valid expression syntax") from exc
    _validate_tree(tree.body)
    return _expression_node(tree.body)


def expressions_equivalent(actual: Any, expected: str) -> bool:
    try:
        actual_expr = parse_safe_expression(actual)
        expected_expr = parse_safe_expression(expected)
        if actual_expr == expected_expr:
            return True
        if actual_expr in (sp.oo, -sp.oo) or expected_expr in (sp.oo, -sp.oo):
            return actual_expr == expected_expr
        return bool(sp.simplify(actual_expr - expected_expr) == 0)
    except (UnsafeResult, TypeError, ValueError, ZeroDivisionError, sp.SympifyError):
        return False


def antiderivatives_equivalent(actual: Any, expected: str) -> bool:
    """Compare indefinite integrals up to an arbitrary additive constant."""

    try:
        actual_expr = parse_safe_expression(actual)
        expected_expr = parse_safe_expression(expected)
        return bool(sp.simplify(sp.diff(actual_expr - expected_expr, _SYMBOLS["x"])) == 0)
    except (UnsafeResult, TypeError, ValueError, ZeroDivisionError, sp.SympifyError):
        return False


def _root_values(value: Any) -> list[sp.Expr] | None:
    if isinstance(value, list):
        values = value
    elif isinstance(value, (tuple, set)):
        values = list(value)
    elif isinstance(value, str):
        try:
            tree = ast.parse(value.replace("^", "**"), mode="eval")
        except SyntaxError:
            return None
        if isinstance(tree.body, ast.Call) and isinstance(tree.body.func, ast.Name) and tree.body.func.id == "set" and not tree.body.args and not tree.body.keywords:
            values = []
        elif isinstance(tree.body, ast.Dict) and not tree.body.keys and not tree.body.values:
            values = []
        elif not isinstance(tree.body, (ast.List, ast.Tuple, ast.Set)):
            return None
        else:
            values = [ast.unparse(item) for item in tree.body.elts]
    else:
        return None
    try:
        parsed = [parse_safe_expression(item if isinstance(item, str) else str(item)) for item in values]
    except UnsafeResult:
        return None
    try:
        if any(not item.is_real or item in (sp.oo, -sp.oo) for item in parsed):
            return None
        return sorted(parsed, key=lambda item: float(item))
    except (TypeError, ValueError, OverflowError):
        return None


def roots_equivalent(actual: Any, expected: list[str]) -> bool:
    actual_roots = _root_values(actual)
    if actual_roots is None:
        return False
    expected_roots = _root_values(expected)
    if expected_roots is None or len(actual_roots) != len(expected_roots):
        return False
    return all(bool(sp.simplify(actual - wanted) == 0) for actual, wanted in zip(actual_roots, expected_roots))


def _body_status(observation: dict[str, Any]) -> tuple[int | None, dict[str, Any] | None]:
    status = observation.get("http_status")
    body = observation.get("body")
    return (status if isinstance(status, int) else None, body if isinstance(body, dict) else None)


def score_solver_case(case: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    """Score one exact-route observation while preserving unresolved outcomes."""

    expected = case["expected"]
    expected_status = expected["status"]
    http_status, body = _body_status(observation)
    if expected_status == "rejected":
        passed = http_status == 422 or (body is not None and body.get("status") == "rejected")
        return {"passed": passed, "counted": False, "outcome": "rejected", "reason": "validation response" if passed else "expected validation rejection"}
    if expected_status == "unresolved":
        passed = http_status == 200 and body is not None and body.get("status") == "unresolved"
        return {"passed": passed, "counted": False, "outcome": "unresolved", "reason": "bounded route declined request" if passed else "expected unresolved response"}
    if http_status != 200 or body is None or body.get("status") != "solved":
        return {"passed": False, "counted": True, "outcome": "failure", "reason": "missing solved response"}
    actual = body.get("result")
    if case["operation"] == "equation":
        expected_result = expected["result"]
        if isinstance(expected_result, str) and expected_result in {"all real x", "no real solutions"}:
            passed = isinstance(actual, str) and actual.strip().casefold() == expected_result
        else:
            passed = roots_equivalent(actual, expected_result)
    elif case["operation"] == "integral" and case["request"].get("lower") is None:
        passed = antiderivatives_equivalent(actual, expected["result"])
    else:
        passed = expressions_equivalent(actual, expected["result"])
    return {"passed": passed, "counted": True, "outcome": "solved", "reason": "result matches" if passed else "result differs"}


def _json_model_answer(text: Any) -> dict[str, Any] | None:
    if not isinstance(text, str) or len(text) > 2000:
        return None
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("status") not in {"solved", "unresolved", "rejected"}:
        return None
    if "result" not in value:
        return None
    return value


def score_ai_case(case: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    """Score an optional machine-readable AI answer with a separate denominator."""

    expected_status = case["expected"]["status"]
    http_status, body = _body_status(observation)
    if expected_status == "rejected":
        passed = http_status == 422 or (
            body is not None and body.get("status") == "rejected"
        )
        return {"passed": passed, "counted": False, "outcome": "validation_rejected", "reason": "shared validation" if passed else "expected validation response"}
    if http_status != 200 or body is None or body.get("status") != "answered":
        return {"passed": False, "counted": expected_status == "solved", "outcome": "failure", "reason": "provider or API failure"}
    if expected_status == "unresolved":
        return {"passed": None, "counted": False, "outcome": "manual_review", "reason": "valid deferred case is outside solved-answer denominator"}
    answer = _json_model_answer(body.get("text"))
    if answer is None:
        return {"passed": False, "counted": True, "outcome": "failure", "reason": "model text is not the required JSON contract"}
    if answer["status"] != expected_status:
        return {"passed": False, "counted": True, "outcome": "mismatch", "reason": "model status differs"}
    if case["operation"] == "equation":
        expected_result = case["expected"]["result"]
        if isinstance(expected_result, str) and expected_result in {"all real x", "no real solutions"}:
            passed = isinstance(answer.get("result"), str) and answer["result"].strip().casefold() == expected_result
        else:
            passed = roots_equivalent(answer.get("result"), expected_result)
    elif case["operation"] == "integral" and case["request"].get("lower") is None:
        passed = antiderivatives_equivalent(answer.get("result"), case["expected"]["result"])
    else:
        passed = expressions_equivalent(answer.get("result"), case["expected"]["result"])
    return {"passed": passed, "counted": True, "outcome": expected_status, "reason": "answer matches" if passed else "answer differs"}


def metric_values(observation: dict[str, Any]) -> dict[str, Any]:
    body = observation.get("body")
    metrics = body.get("metrics") if isinstance(body, dict) else None
    metrics = metrics if isinstance(metrics, dict) else {}
    model_calls = metrics.get("model_calls")
    if model_calls is None:
        model_calls = metrics.get("ai_calls")
    prompt_tokens = metrics.get("prompt_tokens")
    if prompt_tokens is None:
        prompt_tokens = metrics.get("input_tokens")
    completion_tokens = metrics.get("completion_tokens")
    if completion_tokens is None:
        completion_tokens = metrics.get("output_tokens")
    return {
        "elapsed_ms": observation.get("elapsed_ms"),
        "solver_ms": metrics.get("solver_ms"),
        "model_calls": model_calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": metrics.get("total_tokens"),
    }


def _summary_numbers(values: list[Any]) -> dict[str, Any]:
    numbers = [float(value) for value in values if isinstance(value, (int, float)) and math.isfinite(value)]
    if not numbers:
        return {"count": 0, "median": None, "min": None, "max": None}
    return {"count": len(numbers), "median": median(numbers), "min": min(numbers), "max": max(numbers)}


def summarize(observations: list[dict[str, Any]], scores: list[dict[str, Any]]) -> dict[str, Any]:
    counted = [score for score in scores if score.get("counted")]
    metrics = [metric_values(observation) for observation in observations]
    calls = [item["model_calls"] for item in metrics]
    token_fields = {name: [item[name] for item in metrics] for name in ("prompt_tokens", "completion_tokens", "total_tokens")}
    return {
        "observations": len(observations),
        "scored_observations": len(counted),
        "passed": sum(1 for score in counted if score.get("passed")),
        "accuracy": (sum(1 for score in counted if score.get("passed")) / len(counted)) if counted else None,
        "outcomes": dict(Counter(score.get("outcome") for score in scores)),
        "latency_ms": _summary_numbers([item["elapsed_ms"] for item in metrics]),
        "solver_ms": _summary_numbers([item["solver_ms"] for item in metrics]),
        "model_calls": {
            **_summary_numbers(calls),
            "unknown": sum(value is None for value in calls),
        },
        "token_usage": {
            name: {
                **_summary_numbers(values),
                "unknown": sum(value is None for value in values),
            }
            for name, values in token_fields.items()
        },
    }
