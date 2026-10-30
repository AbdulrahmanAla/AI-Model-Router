"""Bounded extraction from chat messages into the exact math contract.

The extractor is deliberately conservative. It recognizes a small set of
calculus and algebra phrases and leaves every other message as language input.
It never evaluates text or parses arbitrary LaTeX.
"""

from __future__ import annotations

import re
from typing import Any

_MAX_MESSAGE_LENGTH = 2000
_MAX_EXPRESSION_LENGTH = 400

_DERIVATIVE_PATTERNS = (
    re.compile(r"^(?:what\s+is\s+|calculate\s+|compute\s+|find\s+)?(?:the\s+)?derivative\s+of\s+(.+)$", re.I),
    re.compile(r"^(?:what\s+is\s+|calculate\s+|compute\s+|find\s+)?differentiate\s+(.+)$", re.I),
    re.compile(r"^d\s*/\s*d\s*x\s+(.+)$", re.I),
)
_INTEGRAL_PATTERNS = (
    re.compile(r"^(?:what\s+is\s+|calculate\s+|compute\s+|find\s+)?(?:the\s+)?integral\s+of\s+(.+)$", re.I),
    re.compile(r"^(?:what\s+is\s+|calculate\s+|compute\s+|find\s+)?integrate\s+(.+)$", re.I),
)
_LIMIT_PATTERN = re.compile(
    r"^(?:what\s+is\s+|calculate\s+|compute\s+|find\s+)?(?:the\s+)?limit\s+of\s+(.+?)\s+as\s+x\s+approaches\s+([^\s]+)(?:\s+from\s+(?:the\s+)?(left|right))?$",
    re.I,
)
_EQUATION_PATTERNS = (
    re.compile(r"^(?:solve|solve\s+for\s+x|find\s+the\s+roots?\s+of|roots?\s+of)\s+(.+)$", re.I),
    re.compile(r"^(?:what\s+are\s+the\s+solutions\s+to)\s+(.+)$", re.I),
)


def _clean(value: str) -> str:
    return re.sub(r"[\s?.!,;:]+$", "", value.strip())


def _candidate(operation: str, expression: str, **fields: Any) -> dict[str, Any] | None:
    expression = _clean(expression)
    if not expression or len(expression) > _MAX_EXPRESSION_LENGTH:
        return None
    payload: dict[str, Any] = {
        "operation": operation,
        "expression": expression,
        "variable": "x",
        "lower": None,
        "upper": None,
        "target": None,
        "direction": None,
    }
    payload.update(fields)
    return payload


def _split_integral_bounds(expression: str) -> tuple[str, str | None, str | None]:
    match = re.match(r"^(.+?)\s+from\s+([^\s]+)\s+to\s+([^\s]+)$", expression, re.I)
    if not match:
        return expression, None, None
    return match.group(1), _clean(match.group(2)), _clean(match.group(3))


def parse_freeform(message: str) -> dict[str, Any] | None:
    """Extract a structured request from one bounded chat message.

    The caller must run the normal Pydantic and solver grammar checks before
    executing the returned payload. Unknown or conversational messages return
    ``None`` and remain language prompts.
    """
    if not isinstance(message, str):
        return None
    text = " ".join(message.split())
    if not text or len(text) > _MAX_MESSAGE_LENGTH:
        return None

    for pattern in _DERIVATIVE_PATTERNS:
        match = pattern.match(text)
        if match:
            expression = re.sub(r"\s+with\s+respect\s+to\s+x$", "", match.group(1), flags=re.I)
            return _candidate("derivative", expression)

    for pattern in _INTEGRAL_PATTERNS:
        match = pattern.match(text)
        if match:
            expression, lower, upper = _split_integral_bounds(match.group(1))
            return _candidate("integral", expression, lower=lower, upper=upper)

    match = _LIMIT_PATTERN.match(text)
    if match:
        direction_word = (match.group(3) or "both").lower()
        direction = "+" if direction_word == "right" else "-" if direction_word == "left" else "both"
        return _candidate("limit", match.group(1), target=_clean(match.group(2)), direction=direction)

    for pattern in _EQUATION_PATTERNS:
        match = pattern.match(text)
        if match:
            return _candidate("equation", match.group(1))

    return None


__all__ = ["parse_freeform"]
