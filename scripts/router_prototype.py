"""Throwaway route-budget prototype for the AI Math Assistant.

This artifact answers one question: how many model calls does a Jev router,
the deterministic fallback, or an AI-only route require? It does not call a
model and must not be used as quality or latency evidence.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    name: str
    operation: str
    supported: bool
    explicit_explanation: bool = False


CASES = (
    Case("derivative", "derivative", True),
    Case("definite integral", "integral", True),
    Case("limit", "limit", True),
    Case("polynomial equation", "equation", True),
    Case("explain derivative", "derivative", True, True),
    Case("natural-language word problem", "unknown", False),
)


def solver_first_route(case: Case) -> str:
    if case.supported and not case.explicit_explanation:
        return "solver"
    return "local_ollama"


def jev_route(case: Case) -> str:
    """Synthetic Jev decision fixture, not a Jev quality claim."""
    return solver_first_route(case)


def summarize(cases: tuple[Case, ...]) -> None:
    deterministic_calls = 0
    jev_calls = 0
    jev_ai_calls = 0
    ai_only_calls = len(cases)
    print("ROUTER PROTOTYPE: synthetic route-budget comparison")
    print("Jev decisions are fixtures. Model quality, latency, and energy are unmeasured.")
    print()
    for case in cases:
        deterministic = solver_first_route(case)
        jev_decision = jev_route(case)
        deterministic_calls += deterministic == "local_ollama"
        jev_calls += 1
        jev_ai_calls += jev_decision == "local_ollama"
        print(
            f"{case.name:28} deterministic={deterministic:12} "
            f"jev_decision={jev_decision:12} jev_ai_call={jev_decision == 'local_ollama'}"
        )
    avoided = ai_only_calls - deterministic_calls
    jev_total = jev_calls + jev_ai_calls
    print()
    print(f"cases={len(cases)}")
    print(f"ai_only_model_calls={ai_only_calls}")
    print(f"deterministic_ai_calls={deterministic_calls}")
    print(f"jev_router_calls={jev_calls}")
    print(f"jev_router_total_model_calls={jev_total}")
    print(f"deterministic_model_calls_avoided={avoided}")
    print("next_evidence=run real Jev and Ollama providers, then measure accuracy, latency, tokens, CPU, and memory")


if __name__ == "__main__":
    summarize(CASES)
