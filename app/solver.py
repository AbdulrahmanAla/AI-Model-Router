"""Bounded, structured math solving for the AI Math Assistant."""

from __future__ import annotations

import ast
from decimal import Decimal, InvalidOperation
import math
import multiprocessing as mp
import os
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import mpmath
import sympy as sp

MAX_EXPRESSION_LENGTH = 400
MAX_AST_NODES = 80
MAX_AST_DEPTH = 12
MAX_INTEGER_DIGITS = 30
MAX_DECIMAL_EXPONENT = 100
MAX_POWER = 20
MAX_NESTED_POWER_PRODUCT = MAX_POWER
MAX_CONCURRENT_SOLVES = 2
SOLVER_TIMEOUT_SECONDS = float(os.getenv("SOLVER_TIMEOUT_SECONDS", "8"))
SOLVER_TIMEOUT_MS = int(os.getenv("SOLVER_TIMEOUT_MS", str(int(SOLVER_TIMEOUT_SECONDS * 1000))))

_CONCURRENCY = threading.BoundedSemaphore(MAX_CONCURRENT_SOLVES)
_SAFE_CHARACTERS = re.compile(r"^[A-Za-z0-9_+\-*/^().,=\s]+$")
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
}
_CONSTANTS = {"pi": sp.pi, "E": sp.E}
_X = sp.Symbol("x", real=True)


class GrammarError(ValueError):
    """The request is outside the intentionally small input grammar."""


class SolveTimeout(RuntimeError):
    """The bounded worker did not finish before its deadline."""


class SolveUnresolved(RuntimeError):
    """The math conclusion is valid but the requested result is unresolved."""


class SolverBusy(RuntimeError):
    """All bounded solver slots are in use."""


@dataclass(frozen=True)
class ParsedExpression:
    expression: sp.Expr
    tree: ast.AST
    source: str


def _normalise_source(source: str) -> str:
    if not isinstance(source, str) or not source.strip():
        raise GrammarError("Enter a structured expression.")
    if len(source) > MAX_EXPRESSION_LENGTH:
        raise GrammarError(f"Expression is limited to {MAX_EXPRESSION_LENGTH} characters.")
    if not _SAFE_CHARACTERS.fullmatch(source):
        raise GrammarError("Use numbers, x, parentheses, arithmetic operators, and supported functions only.")
    return source.replace("^", "**").strip()


def _tree_limits(tree: ast.AST) -> None:
    nodes = 0
    stack: list[tuple[ast.AST, int]] = [(tree, 0)]
    while stack:
        node, depth = stack.pop()
        nodes += 1
        if nodes > MAX_AST_NODES or depth > MAX_AST_DEPTH:
            raise GrammarError("Expression is too large or deeply nested.")
        for child in ast.iter_child_nodes(node):
            stack.append((child, depth + 1))


def _validate_power_shapes(tree: ast.AST) -> None:
    """Reject exponent expressions before constructing any SymPy power."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Pow):
            continue
        exponent = node.right
        if isinstance(exponent, ast.Constant) and isinstance(exponent.value, int) and not isinstance(exponent.value, bool):
            continue
        if isinstance(exponent, ast.UnaryOp) and isinstance(exponent.op, (ast.UAdd, ast.USub)) and isinstance(exponent.operand, ast.Constant) and isinstance(exponent.operand.value, int) and not isinstance(exponent.operand.value, bool):
            continue
        raise GrammarError("Powers require a small integer literal exponent.")
    def nested_power_product(node: ast.AST) -> int:
        children = list(ast.iter_child_nodes(node))
        child_product = max((nested_power_product(child) for child in children), default=1)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            exponent = node.right
            if isinstance(exponent, ast.Constant):
                magnitude = abs(int(exponent.value))
            elif isinstance(exponent, ast.UnaryOp) and isinstance(exponent.operand, ast.Constant):
                magnitude = abs(int(exponent.operand.value))
            else:
                magnitude = MAX_NESTED_POWER_PRODUCT + 1
            child_product = max(child_product, magnitude * nested_power_product(node.left))
        return child_product
    if nested_power_product(tree) > MAX_NESTED_POWER_PRODUCT:
        raise GrammarError("Nested powers are limited to keep exact work bounded.")


_NUMERIC_LITERAL = re.compile(r"^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def _exact_numeric_literal(literal: str) -> sp.Expr:
    """Build a bounded exact number from the source spelling of a literal."""
    normalized = literal.replace("_", "")
    if not _NUMERIC_LITERAL.fullmatch(normalized):
        raise GrammarError("Unsupported numeric constant.")
    digits = re.sub(r"[^0-9]", "", normalized)
    if len(digits) > MAX_INTEGER_DIGITS:
        raise GrammarError("Numeric constants are too large.")
    exponent_match = re.search(r"[eE]([+-]?\d+)$", normalized)
    exponent = int(exponent_match.group(1)) if exponent_match else 0
    if abs(exponent) > MAX_DECIMAL_EXPONENT:
        raise GrammarError("Scientific exponents are too large.")
    try:
        decimal = Decimal(normalized)
    except (InvalidOperation, ValueError) as exc:
        raise GrammarError("Numeric constants must be finite.") from exc
    if not decimal.is_finite():
        raise GrammarError("Numeric constants must be finite.")
    if decimal.copy_abs() >= Decimal(10) ** MAX_INTEGER_DIGITS:
        raise GrammarError("Numeric constants are too large.")
    return sp.Rational(normalized)


def _number(value: Any, *, literal: str | None = None) -> sp.Expr:
    if isinstance(value, bool):
        raise GrammarError("Boolean values are not math inputs.")
    if literal is not None:
        return _exact_numeric_literal(literal)
    if isinstance(value, int):
        if len(str(abs(value))) > MAX_INTEGER_DIGITS:
            raise GrammarError("Numeric constants are too large.")
        return sp.Integer(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise GrammarError("Numeric constants must be finite.")
        rendered = repr(value)
        if len(re.sub(r"[^0-9]", "", rendered)) > MAX_INTEGER_DIGITS:
            raise GrammarError("Numeric constants are too large.")
        return sp.Rational(str(value))
    raise GrammarError("Unsupported numeric constant.")


def _compile(node: ast.AST, *, allow_oo: bool, source: str | None = None) -> sp.Expr:
    if isinstance(node, ast.Expression):
        return _compile(node.body, allow_oo=allow_oo, source=source)
    if isinstance(node, ast.Constant):
        literal = ast.get_source_segment(source, node) if source is not None else None
        return _number(node.value, literal=literal)
    if isinstance(node, ast.Name):
        if node.id == "x":
            return _X
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        if allow_oo and node.id == "oo":
            return sp.oo
        raise GrammarError(f"Unknown name '{node.id}'.")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = _compile(node.operand, allow_oo=allow_oo, source=source)
        return operand if isinstance(node.op, ast.UAdd) else -operand
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Pow):
            exponent = _compile(node.right, allow_oo=allow_oo, source=source)
            if not exponent.is_Integer or abs(int(exponent)) > MAX_POWER:
                raise GrammarError(f"Powers must be integer exponents from {-MAX_POWER} to {MAX_POWER}.")
            left = _compile(node.left, allow_oo=allow_oo, source=source)
            return left**exponent
        left = _compile(node.left, allow_oo=allow_oo, source=source)
        right = _compile(node.right, allow_oo=allow_oo, source=source)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise GrammarError("Division by zero is not a valid input.")
            return left / right
        raise GrammarError("That arithmetic operator is not supported.")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise GrammarError("Only supported one-argument math functions are allowed.")
        if len(node.args) != 1 or node.keywords:
            raise GrammarError("Math functions take one positional argument.")
        return _FUNCTIONS[node.func.id](_compile(node.args[0], allow_oo=allow_oo, source=source))
    raise GrammarError("That expression is outside the supported grammar.")


def parse_expression(source: str, *, allow_oo: bool = False) -> ParsedExpression:
    normalised = _normalise_source(source)
    try:
        tree = ast.parse(normalised, mode="eval")
    except (SyntaxError, ValueError) as exc:
        raise GrammarError("Use a valid structured expression with explicit multiplication.") from exc
    _tree_limits(tree)
    _validate_power_shapes(tree)
    expression = _compile(tree, allow_oo=allow_oo, source=normalised)
    _validate_constant_function_values(tree, normalised)
    if expression.free_symbols - {_X}:
        raise GrammarError("Only the real variable x is supported.")
    is_allowed_infinite_constant = allow_oo and expression in (sp.oo, -sp.oo)
    if expression in (sp.zoo, sp.nan) or (expression.is_real is False and not is_allowed_infinite_constant):
        raise GrammarError("Only defined real-valued expressions are supported.")
    return ParsedExpression(expression=expression, tree=tree, source=normalised)


def _contains_variable(node: ast.AST) -> bool:
    return any(isinstance(item, ast.Name) and item.id == "x" for item in ast.walk(node))


def _contains_variable_function_call(node: ast.AST) -> bool:
    return any(isinstance(item, ast.Call) and _contains_variable(item) for item in ast.walk(node))


def _validate_constant_function_values(tree: ast.AST, source: str) -> None:
    """Reject complex or undefined constant function calls in real input."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _contains_variable(node):
            continue
        value = _compile(node, allow_oo=False, source=source)
        if value in (sp.zoo, sp.nan) or value.is_real is not True:
            raise GrammarError("Only defined real-valued expressions are supported.")


def _has_variable_denominator(node: ast.AST, *, source: str | None = None) -> bool:
    for item in ast.walk(node):
        if isinstance(item, ast.BinOp) and isinstance(item.op, ast.Div) and _contains_variable(item.right):
            return True
        if isinstance(item, ast.BinOp) and isinstance(item.op, ast.Pow) and _contains_variable(item.left):
            try:
                exponent = _compile(item.right, allow_oo=False, source=source)
            except GrammarError:
                return True
            if exponent.is_negative:
                return True
    return False


def parse_constant(source: str) -> sp.Expr:
    parsed = parse_expression(source, allow_oo=True)
    if parsed.expression.free_symbols:
        raise GrammarError("Bounds and limit targets must be constants.")
    if parsed.expression in (sp.zoo, sp.nan):
        raise GrammarError("That constant is undefined.")
    return parsed.expression


def validate_structured_payload(payload: dict[str, Any]) -> None:
    """Validate the bounded public grammar without attempting to solve it.

    Equation validation deliberately stops before polynomial expansion. Common
    function equations are valid structured requests and can be offered to an
    AI fallback even when the exact polynomial route cannot solve them.
    """
    operation = payload.get("operation")
    expression = payload.get("expression")
    if not isinstance(operation, str) or not isinstance(expression, str):
        raise GrammarError("A structured operation and expression are required.")
    if operation not in {"derivative", "integral", "limit", "equation"}:
        raise GrammarError("That operation is not supported.")
    if operation == "equation":
        if expression.count("=") > 1:
            raise GrammarError("An equation may contain one equals sign.")
        if "=" in expression:
            left_source, right_source = (part.strip() for part in expression.split("=", 1))
            left = parse_expression(left_source)
            right = parse_expression(right_source)
            if _has_variable_denominator(left.tree.body, source=left.source) or _has_variable_denominator(right.tree.body, source=right.source):
                raise GrammarError("Equations with a variable in a denominator are not supported.")
        else:
            parsed = parse_expression(expression)
            if _has_variable_denominator(parsed.tree.body, source=parsed.source):
                raise GrammarError("Equations with a variable in a denominator are not supported.")
        return
    parse_expression(expression)
    if operation == "integral" and payload.get("lower") is not None:
        if payload.get("upper") is None:
            raise GrammarError("Integral bounds must be provided together.")
        parse_constant(payload["lower"])
        parse_constant(payload["upper"])
    if operation == "limit":
        if payload.get("target") is None:
            raise GrammarError("A limit target is required.")
        parse_constant(payload["target"])


def _sstr(expression: sp.Expr) -> str:
    return sp.sstr(expression)


def _latex(expression: sp.Expr) -> str:
    return sp.latex(expression)


def _raw_point_is_real(tree: ast.AST | None, source: str | None, point: sp.Expr) -> bool:
    """Check raw function and denominator restrictions at one real point."""
    if tree is None or source is None:
        return True
    try:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                value = sp.simplify(_compile(node, allow_oo=False, source=source).subs(_X, point))
                if value in (sp.zoo, sp.nan) or value.is_real is not True:
                    return False
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and _contains_variable(node.right):
                denominator = _compile(node.right, allow_oo=False, source=source)
                value = sp.simplify(denominator.subs(_X, point))
                if value in (0, sp.zoo, sp.nan) or value.is_real is not True:
                    return False
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow) and _contains_variable(node.left):
                exponent = _compile(node.right, allow_oo=False, source=source)
                if exponent.is_negative:
                    denominator = _compile(node.left, allow_oo=False, source=source)
                    value = sp.simplify(denominator.subs(_X, point))
                    if value in (0, sp.zoo, sp.nan) or value.is_real is not True:
                        return False
    except Exception:
        return False
    return True


def _verify_derivative(original: sp.Expr, result: sp.Expr, raw_tree: ast.AST | None = None, source: str | None = None) -> dict[str, str]:
    original_fn = sp.lambdify(_X, original, "mpmath")
    result_fn = sp.lambdify(_X, result, "mpmath")
    valid = 0
    mismatches = 0
    for point in (-1.25, -0.5, 0.4, 1.3, 2.1):
        try:
            x = mpmath.mpf(point)
            h = mpmath.mpf("1e-6")
            if not all(_raw_point_is_real(raw_tree, source, sp.Float(sample)) for sample in (point, point - 1e-6, point + 1e-6)):
                continue
            expected = (original_fn(x + h) - original_fn(x - h)) / (2 * h)
            actual = result_fn(x)
            if not mpmath.isfinite(expected) or not mpmath.isfinite(actual):
                continue
            if abs(mpmath.im(expected)) > 1e-8 or abs(mpmath.im(actual)) > 1e-8:
                continue
            if abs(expected - actual) <= max(1e-6, abs(expected) * 1e-5):
                valid += 1
            else:
                mismatches += 1
        except Exception:
            continue
    if mismatches:
        return {"status": "failed", "method": "finite-difference samples", "detail": f"A valid real sample disagreed at {mismatches} point(s)."}
    if valid >= 2:
        return {"status": "numerical_evidence", "method": "finite-difference samples", "detail": f"Matched {valid} valid real sample points."}
    return {"status": "not_checked", "method": "finite-difference samples", "detail": "No safe real sample points were available."}


def _verify_antiderivative(original: sp.Expr, result: sp.Expr) -> dict[str, str]:
    try:
        residual = sp.simplify(sp.diff(result, _X) - original)
    except Exception:
        return {"status": "not_checked", "method": "symbolic derivative residual", "detail": "The result could not be checked symbolically."}
    if residual == 0:
        return {"status": "symbolic_check", "method": "differentiate antiderivative", "detail": "The derivative residual simplifies to zero on the stated real domain."}
    return {"status": "failed", "method": "differentiate antiderivative", "detail": "The derivative residual did not simplify to zero."}


def _verify_branch_antiderivative(original: sp.Expr, result: sp.Expr) -> dict[str, str]:
    """Check a real logarithmic primitive away from its excluded zeros."""
    try:
        residual = sp.diff(result, _X) - original
        residual_fn = sp.lambdify(_X, residual, "mpmath")
        valid = 0
        for point in (-2.1, -0.7, 0.4, 1.6, 3.2):
            value = residual_fn(point)
            if mpmath.isfinite(value) and abs(value) <= 1e-8:
                valid += 1
        if valid >= 3:
            return {
                "status": "numerical_evidence",
                "method": "sampled real logarithmic branch",
                "detail": f"The derivative matched at {valid} safe real sample points away from logarithm zeros.",
            }
    except Exception:
        pass
    return {"status": "failed", "method": "differentiate real logarithmic branch", "detail": "The real branch could not be checked safely."}


def _real_log_antiderivative(result: sp.Expr) -> tuple[sp.Expr, bool]:
    changed = False

    def replace_log(item: sp.Expr) -> sp.Expr:
        nonlocal changed
        if item.func == sp.log and item.args and item.args[0].is_positive is not True:
            changed = True
            return sp.log(sp.Abs(item.args[0]))
        return item

    transformed = result.replace(lambda item: item.func == sp.log and item.args and item.args[0].is_positive is not True, replace_log)
    return transformed, changed


def _verify_definite_integral(original: sp.Expr, result: sp.Expr, lower: sp.Expr, upper: sp.Expr) -> dict[str, str]:
    if lower.is_finite is not True or upper.is_finite is not True:
        return {"status": "not_checked", "method": "exact definite integral", "detail": "The exact result was returned without independent numerical evidence for an infinite bound."}
    try:
        fn = sp.lambdify(_X, original, "mpmath")
        numeric = mpmath.quad(fn, [float(lower), float(upper)])
        expected = complex(sp.N(result, 16))
        if abs(complex(numeric) - expected) <= max(1e-7, abs(expected) * 1e-6):
            return {"status": "numerical_evidence", "method": "independent numerical quadrature", "detail": "Quadrature agrees with the exact result."}
    except Exception:
        pass
    return {"status": "not_checked", "method": "independent numerical quadrature", "detail": "The exact result was returned without a safe quadrature check."}


def _verify_equation(expression: sp.Expr, roots: list[sp.Expr]) -> dict[str, str]:
    try:
        if all(sp.simplify(expression.subs(_X, root)) == 0 for root in roots):
            return {"status": "symbolic_check", "method": "root substitution", "detail": "Every returned real root satisfies the equation."}
    except Exception:
        pass
    return {"status": "failed", "method": "root substitution", "detail": "A returned root did not satisfy the equation."}


def _open_interval(lower: sp.Expr, upper: sp.Expr) -> sp.Set:
    return sp.Interval.open(lower, upper)


def _domain_contains_open_interval(domain: sp.Set, lower: sp.Expr, upper: sp.Expr) -> bool | None:
    """Return a proof that the open interval is in a real domain.

    SymPy can leave set containment undecidable for periodic or image-set
    domains. In that case callers must treat the domain as unresolved rather
    than converting a few samples into a false proof.
    """
    interior = _open_interval(lower, upper)
    try:
        subset = interior.is_subset(domain)
        if subset is True or subset is False:
            return subset
        missing = sp.Complement(interior, domain)
        if missing == sp.EmptySet or missing.is_empty is True:
            return True
        if missing.is_empty is False:
            return False
    except Exception:
        pass
    return None


def _check_raw_function_domains(tree: ast.AST, lower: sp.Expr, upper: sp.Expr, source: str) -> None:
    """Prove the original function calls are real throughout the open interval."""
    if lower == upper:
        return
    interior = _open_interval(lower, upper)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or not node.args:
            continue
        function_name = node.func.id
        if function_name not in {"sqrt", "log", "asin", "acos", "tan"}:
            continue
        try:
            raw_function = _compile(node, allow_oo=False, source=source)
            domain = sp.calculus.util.continuous_domain(raw_function, _X, sp.S.Reals)
        except Exception as exc:
            raise RuntimeError("The function domain is unresolved across the interval.") from exc
        contained = _domain_contains_open_interval(domain, lower, upper)
        if contained is False:
            if function_name == "sqrt":
                message = "The square-root domain is outside the real interval."
            elif function_name == "log":
                message = "The logarithm domain is outside the real interval."
            elif function_name in {"asin", "acos"}:
                message = "The inverse-trigonometric domain is outside the real interval."
            else:
                message = "The tangent is undefined inside the interval."
            raise RuntimeError(message)
        if contained is None:
            # A periodic tangent domain often cannot be represented as a
            # decidable subset. Solve its poles exactly when possible.
            if function_name == "tan":
                try:
                    poles = sp.solveset(sp.cos(raw_function.args[0]), _X, domain=interior)
                except Exception as exc:
                    raise RuntimeError("The tangent domain is unresolved across the interval.") from exc
                if poles == sp.EmptySet:
                    continue
                if isinstance(poles, sp.FiniteSet):
                    raise RuntimeError("The tangent is undefined inside the interval.")
            raise RuntimeError("The function domain is unresolved across the interval.")


def _check_raw_denominator_domains(tree: ast.AST, lower: sp.Expr, upper: sp.Expr, source: str) -> None:
    """Reject a denominator hole that simplification could otherwise erase."""
    denominators: list[sp.Expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and _contains_variable(node.right):
            denominators.append(_compile(node.right, allow_oo=False, source=source))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow) and _contains_variable(node.left):
            exponent = _compile(node.right, allow_oo=False, source=source)
            if exponent.is_negative:
                denominators.append(_compile(node.left, allow_oo=False, source=source))
    for denominator in denominators:
        try:
            roots = sp.solveset(denominator, _X, domain=_open_interval(lower, upper))
        except Exception as exc:
            raise RuntimeError("The denominator domain is unresolved across the interval.") from exc
        if roots == sp.EmptySet or roots.is_empty is True:
            continue
        if isinstance(roots, sp.FiniteSet):
            raise RuntimeError("The interval contains a denominator hole.")
        raise RuntimeError("The denominator domain is unresolved across the interval.")


def _check_limit_approach_domain(tree: ast.AST, source: str, target: sp.Expr, direction: str) -> None:
    """Require raw-domain samples in every direction used by the limit.

    SymPy may simplify away restrictions from the original expression, such as
    ``sqrt(x)**2`` becoming ``x``.  Sampling the parsed expression itself keeps
    that information without trying to symbolically reconstruct every possible
    real domain.  This is deliberately conservative: failure to find a safe
    approach point yields an unresolved result rather than an unverified answer.
    """
    finite_target = target.is_finite is True
    if finite_target:
        distances = (sp.Rational(1, 1), sp.Rational(1, 10), sp.Rational(1, 100), sp.Rational(1, 1000), sp.Rational(1, 100000))
        sides = ("-", "+") if direction == "both" else (direction,)
        for side in sides:
            sign = -1 if side == "-" else 1
            valid = any(_raw_point_is_real(tree, source, target + sign * distance) for distance in distances)
            if not valid:
                raise SolveUnresolved("The original real domain does not approach the target from the requested direction.")
        return

    # At infinity, use increasingly distant real samples in the requested
    # direction.  Two successful samples avoid accepting a bounded domain that
    # happens to contain one arbitrary probe point.
    sign = 1 if target == sp.oo else -1
    distances = (10, 100, 1000, 1000000)
    valid = sum(_raw_point_is_real(tree, source, sign * distance) for distance in distances)
    if valid < 2:
        raise SolveUnresolved("The original real domain does not extend toward the requested infinite target.")


def _verify_limit_numeric(original: sp.Expr, result: sp.Expr, target: sp.Expr, direction: str, raw_tree: ast.AST | None = None, source: str | None = None) -> dict[str, str]:
    if target.is_finite is not True or result in (sp.oo, -sp.oo, sp.zoo, sp.nan) or result.has(sp.Limit, sp.AccumBounds):
        return {"status": "not_checked", "method": "near-target samples", "detail": "A finite real sample check was not available."}
    try:
        fn = sp.lambdify(_X, original, "mpmath")
        expected = complex(sp.N(result, 16))
        if abs(expected.imag) > 1e-8:
            return {"status": "not_checked", "method": "near-target samples", "detail": "The limit result is not real-valued."}
        matched = 0
        target_value = mpmath.mpf(str(float(sp.N(target, 16))))
        for distance in (mpmath.mpf("1e-2"), mpmath.mpf("1e-4"), mpmath.mpf("1e-6"), mpmath.mpf("1e-8"), mpmath.mpf("1e-10")):
            offsets = (-distance, distance) if direction == "both" else ((distance if direction == "+" else -distance),)
            for offset in offsets:
                if not _raw_point_is_real(raw_tree, source, sp.Float(target_value + offset)):
                    continue
                value = fn(target_value + offset)
                if abs(mpmath.im(value)) <= 1e-8 and abs(complex(value) - expected) <= max(1e-5, abs(expected) * 1e-4):
                    matched += 1
        needed = 3 if direction != "both" else 6
        if matched >= needed:
            return {"status": "numerical_evidence", "method": "near-target samples", "detail": "Safe samples agree with the symbolic limit."}
    except Exception:
        pass
    return {"status": "not_checked", "method": "near-target samples", "detail": "The symbolic limit was returned without a safe numerical check."}


def _bounded_steps(items: list[str]) -> list[str]:
    """Keep educational route descriptions bounded like every other response field."""
    return [item[:500] for item in items[:8]]


def _verification_step(verification: dict[str, str]) -> str:
    status = verification.get("status", "not_checked")
    detail = verification.get("detail")
    return f"Verification ({status}): {detail}" if detail else f"Verification status: {status}."


def _solved_steps(
    operation: str,
    source: str,
    result: str,
    verification: dict[str, str],
    *,
    expression: sp.Expr | None = None,
    lower: sp.Expr | None = None,
    upper: sp.Expr | None = None,
    target: sp.Expr | None = None,
    direction: str | None = None,
    expanded_equation: str | None = None,
    polynomial_degree: int | None = None,
    branch_sensitive: bool = False,
) -> list[str]:
    """Describe the bounded exact route in language suitable for the result card."""
    if operation == "derivative":
        steps = [f"Read the function as f(x) = {source}."]
        if expression is not None and expression.is_Add:
            steps.append("Differentiate each term and combine the derivatives.")
        elif expression is not None and expression.is_Mul:
            steps.append("Apply the product rule to the factors that depend on x.")
        elif expression is not None and expression.is_Pow:
            steps.append("Apply the power rule to the expression in x.")
        else:
            steps.append("Apply the supported differentiation rules with respect to x.")
        steps.extend([f"Simplify the derivative to {result}.", _verification_step(verification)])
        return _bounded_steps(steps)

    if operation == "integral":
        steps = [f"Read the integrand as {source}."]
        if lower is None and upper is None:
            steps.append("Find an antiderivative with respect to x.")
            if branch_sensitive:
                steps.append("Use the real logarithmic branch log(Abs(...)) and keep its nonzero-domain restriction.")
            steps.append(f"Display the antiderivative as {result}; the arbitrary constant C is omitted.")
        else:
            steps.append(f"Check the original real domain across [{_sstr(lower)}, {_sstr(upper)}].")
            steps.append(f"Evaluate the definite integral from {_sstr(lower)} to {_sstr(upper)}.")
            steps.append(f"Simplify the bounded result to {result}.")
        steps.append(_verification_step(verification))
        return _bounded_steps(steps)

    if operation == "limit":
        direction_text = "both sides" if direction == "both" else ("the right side" if direction == "+" else "the left side")
        steps = [f"Read the expression {source} as x approaches {_sstr(target)}."]
        steps.append("Check the original real domain for safe points approaching the target.")
        if direction == "both":
            steps.append("Compute the left-hand and right-hand limits, then compare them.")
        else:
            steps.append(f"Compute the one-sided limit from {direction_text}.")
        steps.extend([f"Simplify the limit to {result}.", _verification_step(verification)])
        return _bounded_steps(steps)

    if operation == "equation":
        steps = [f"Parse the equation {source} with the bounded real expression grammar."]
        if "=" in source:
            steps.append("Move both sides to one polynomial expression equal to zero.")
        else:
            steps.append("Treat the expression as an equation equal to zero.")
        if expanded_equation is not None:
            steps.append(f"Expand the polynomial: {expanded_equation} = 0.")
        if result == "all real x":
            steps.append("Recognize a polynomial identity, so every real x is a solution.")
        elif result == "no real solutions":
            steps.append("Recognize a nonzero constant equation, so no real solution exists.")
        else:
            degree_text = f" of degree {polynomial_degree}" if polynomial_degree is not None else ""
            steps.append(f"Solve the real polynomial{degree_text} for its candidate roots.")
            steps.append(f"Substitute the returned roots to verify the solution set {result}.")
        steps.append(_verification_step(verification))
        return _bounded_steps(steps)

    return _bounded_steps([f"Compute the exact result {result}.", _verification_step(verification)])


def _unresolved_steps(payload: dict[str, Any], note: str) -> list[str]:
    """Explain where an unresolved exact route stopped without inventing a result."""
    operation = payload.get("operation", "request")
    source = payload.get("expression", "the supplied expression")
    return _bounded_steps([
        f"Read the {operation} request for {source}.",
        f"Stop before returning an exact answer: {note}",
    ])


def _compute(payload: dict[str, Any]) -> dict[str, Any]:
    operation = payload["operation"]
    source = payload["expression"]
    validate_structured_payload(payload)
    if operation == "equation":
        if source.count("=") > 1:
            raise GrammarError("An equation may contain one equals sign.")
        if "=" in source:
            left_source, right_source = (part.strip() for part in source.split("=", 1))
            left = parse_expression(left_source)
            right = parse_expression(right_source)
            raw_tree = ast.parse(_normalise_source(left_source), mode="eval")
            raw_right_tree = ast.parse(_normalise_source(right_source), mode="eval")
            if _has_variable_denominator(raw_tree.body, source=_normalise_source(left_source)) or _has_variable_denominator(raw_right_tree.body, source=_normalise_source(right_source)):
                raise GrammarError("Equations with a variable in a denominator are not supported.")
            if _contains_variable_function_call(raw_tree.body) or _contains_variable_function_call(raw_right_tree.body):
                raise RuntimeError("Only real polynomial equations are supported.")
            equation_input = left.expression - right.expression
        else:
            parsed = parse_expression(source)
            if _has_variable_denominator(parsed.tree.body, source=parsed.source):
                raise GrammarError("Equations with a variable in a denominator are not supported.")
            if _contains_variable_function_call(parsed.tree.body):
                raise RuntimeError("Only real polynomial equations are supported.")
            equation_input = parsed.expression
        try:
            sp.Poly(equation_input, _X)
        except Exception as exc:
            raise RuntimeError("Only real polynomial equations are supported.") from exc
        equation = sp.expand(equation_input)
        polynomial = sp.Poly(equation, _X)
        if polynomial.degree() > 4:
            raise RuntimeError("This polynomial is outside the supported degree-four boundary.")
        if polynomial.is_zero:
            result = "all real x"
            roots: list[sp.Expr] = []
            verification = {"status": "symbolic_check", "method": "polynomial identity", "detail": "Both sides are identical for every real x."}
        elif polynomial.degree() == 0:
            result = "no real solutions"
            roots = []
            verification = {"status": "symbolic_check", "method": "constant equation", "detail": "The constant equation has no real root."}
        else:
            try:
                candidates = sp.solve(equation, _X)
            except Exception as exc:
                raise RuntimeError("The equation solver could not finish.") from exc
            roots = []
            for candidate in candidates:
                try:
                    if candidate.is_real is True or abs(complex(sp.N(candidate, 16)).imag) < 1e-10:
                        roots.append(candidate)
                except Exception:
                    continue
            roots.sort(key=lambda item: float(sp.N(item)))
            result = "{" + ", ".join(_sstr(root) for root in roots) + "}"
            verification = _verify_equation(equation, roots)
        latex = result if result.startswith("all ") or result.startswith("no ") else _latex(sp.FiniteSet(*roots))
        return {
            "result": result,
            "latex": latex,
            "verification": verification,
            "notes": ["The returned set is the complete real polynomial solution set."],
            "steps": _solved_steps(
                operation,
                source,
                result,
                verification,
                expanded_equation=_sstr(equation),
                polynomial_degree=None if polynomial.is_zero else int(polynomial.degree()),
            ),
        }

    parsed = parse_expression(source)
    expression = parsed.expression
    if operation == "derivative":
        result_expr = sp.diff(expression, _X)
        result_text = _sstr(result_expr)
        verification = _verify_derivative(expression, result_expr, parsed.tree, parsed.source)
        return {"result": result_text, "latex": _latex(result_expr), "verification": verification, "notes": [], "steps": _solved_steps(operation, source, result_text, verification, expression=expression)}
    if operation == "integral":
        if payload.get("lower") is None and payload.get("upper") is None:
            result_expr = sp.integrate(expression, _X)
            if result_expr.has(sp.Integral):
                raise RuntimeError("The antiderivative is unresolved.")
            branch_sensitive = False
            if result_expr.has(sp.log):
                transformed, branch_sensitive = _real_log_antiderivative(result_expr)
                if branch_sensitive:
                    verification = _verify_branch_antiderivative(expression, transformed)
                    if verification["status"] != "numerical_evidence":
                        raise RuntimeError("The real logarithmic branch is unresolved.")
                    result_expr = transformed
                else:
                    verification = _verify_antiderivative(expression, result_expr)
            else:
                verification = _verify_antiderivative(expression, result_expr)
            notes = ["The arbitrary constant C is omitted."]
            if branch_sensitive:
                notes.append("Real logarithms use Abs and are valid on intervals where each logarithm argument is nonzero.")
            result_text = _sstr(result_expr)
            return {"result": result_text, "latex": _latex(result_expr), "verification": verification, "notes": notes, "steps": _solved_steps(operation, source, result_text, verification, expression=expression, branch_sensitive=branch_sensitive)}
        lower = parse_constant(payload["lower"])
        upper = parse_constant(payload["upper"])
        if (lower not in (sp.oo, -sp.oo) and lower.is_real is not True) or (upper not in (sp.oo, -sp.oo) and upper.is_real is not True):
            raise RuntimeError("The integral bounds are not real.")
        if lower == sp.oo or upper == -sp.oo:
            raise RuntimeError("Integral bounds must be ordered from lower to upper.")
        if lower.is_finite is True and upper.is_finite is True and bool(lower > upper):
            raise RuntimeError("Integral bounds must be ordered from lower to upper.")
        _check_raw_function_domains(parsed.tree, lower, upper, parsed.source)
        _check_raw_denominator_domains(parsed.tree, lower, upper, parsed.source)
        if lower == upper:
            result_expr = sp.Integer(0)
        else:
            try:
                singular = sp.singularities(expression, _X)
            except Exception as exc:
                raise RuntimeError("The real domain of this integral is unresolved.") from exc
            if singular is not sp.EmptySet:
                for item in singular:
                    if item.is_real is True and (lower.is_finite is not True or bool(item > lower)) and (upper.is_finite is not True or bool(item < upper)):
                        raise RuntimeError("The interval contains a singularity.")
            try:
                domain = sp.calculus.util.continuous_domain(expression, _X, sp.S.Reals)
                midpoint = (lower + upper) / 2 if lower.is_finite is True and upper.is_finite is True else (lower + 1 if lower.is_finite is True else upper - 1)
                if domain.contains(midpoint) != sp.S.true:
                    raise RuntimeError("The integrand is not real and continuous across the interval.")
                contained = _domain_contains_open_interval(domain, lower, upper)
                if contained is False:
                    raise RuntimeError("The integrand is not real and continuous across the interval.")
                if contained is None:
                    raise RuntimeError("The real domain of this integral is unresolved.")
            except RuntimeError:
                raise
            except Exception as exc:
                raise RuntimeError("The real domain of this integral is unresolved.") from exc
            result_expr = sp.integrate(expression, (_X, lower, upper))
        if result_expr.has(sp.Integral, sp.AccumBounds) or result_expr in (sp.nan, sp.zoo, sp.oo, -sp.oo) or result_expr.is_real is False:
            raise RuntimeError("The definite integral is unresolved.")
        result_text = _sstr(result_expr)
        verification = _verify_definite_integral(expression, result_expr, lower, upper)
        return {"result": result_text, "latex": _latex(result_expr), "verification": verification, "notes": [], "steps": _solved_steps(operation, source, result_text, verification, expression=expression, lower=lower, upper=upper)}
    if operation == "limit":
        target = parse_constant(payload["target"])
        direction = payload.get("direction") or "both"
        _check_limit_approach_domain(parsed.tree, parsed.source, target, direction)
        if direction == "both":
            left = sp.limit(expression, _X, target, dir="-")
            right = sp.limit(expression, _X, target, dir="+")
            same = left == right
            if not same:
                try:
                    same = sp.simplify(left - right) == 0
                except Exception:
                    same = False
            if not same:
                raise SolveUnresolved(
                    "The two-sided limit does not exist because the left-hand limit is "
                    f"{_sstr(left)} and the right-hand limit is {_sstr(right)}."
                )
            result_expr = left
        else:
            result_expr = sp.limit(expression, _X, target, dir=direction)
        if result_expr in (sp.nan, sp.zoo) or result_expr.has(sp.Limit, sp.AccumBounds):
            raise RuntimeError("The limit is unresolved.")
        verification = _verify_limit_numeric(expression, result_expr, target, direction, parsed.tree, parsed.source)
        result_text = _sstr(result_expr)
        return {"result": result_text, "latex": _latex(result_expr), "verification": verification, "notes": [], "steps": _solved_steps(operation, source, result_text, verification, expression=expression, target=target, direction=direction)}
    raise GrammarError("That operation is not supported.")


def _worker(payload: dict[str, Any], result_queue: Any) -> None:
    started = time.perf_counter()
    try:
        data = _compute(payload)
        data["solver_ms"] = round((time.perf_counter() - started) * 1000, 3)
        result_queue.put({"ok": True, "data": data})
    except GrammarError as exc:
        result_queue.put({"ok": False, "kind": "grammar", "message": str(exc)})
    except SolveUnresolved as exc:
        result_queue.put({"ok": False, "kind": "unresolved", "message": str(exc)})
    except Exception as exc:
        result_queue.put({"ok": False, "kind": "unresolved", "message": str(exc)})


def run_bounded(payload: dict[str, Any]) -> dict[str, Any]:
    if not _CONCURRENCY.acquire(blocking=False):
        raise SolverBusy
    result_queue = None
    try:
        context = mp.get_context("spawn")
        result_queue = context.Queue(maxsize=1)
        process = context.Process(target=_worker, args=(payload, result_queue), daemon=True)
        process.start()
        process.join(SOLVER_TIMEOUT_MS / 1000)
        if process.is_alive():
            process.terminate()
            process.join(0.2)
            raise SolveTimeout
        try:
            result = result_queue.get(timeout=0.25)
        except queue.Empty as exc:
            raise RuntimeError("The solver exited without a result.") from exc
        if result.get("ok"):
            return result["data"]
        if result.get("kind") == "grammar":
            raise GrammarError(result.get("message", "Invalid expression."))
        if result.get("kind") == "unresolved":
            raise SolveUnresolved(result.get("message", "The solver could not finish."))
        raise RuntimeError(result.get("message", "The solver could not finish."))
    finally:
        if result_queue is not None:
            result_queue.close()
        _CONCURRENCY.release()
