"""Run the four-minute demo prompts as a fast local acceptance check."""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


BASE_URL = "http://127.0.0.1:8020"
CASES = [
    ("Hi", "ai"),
    ("What is Python?", "ai"),
    ("What is the derivative of sin(x)?", "solver"),
    ("Differentiate x^3 + 2x", "solver"),
    ("What is the integral of 2x + cos(x)?", "solver"),
    ("Find the limit of sin(x)/x as x approaches 0", "solver"),
    ("Solve x^2 - 4 = 0", "solver"),
]


def post(message: str) -> dict[str, object]:
    request = urllib.request.Request(
        f"{BASE_URL}/api/chat",
        data=json.dumps({"message": message}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def main() -> int:
    failures: list[str] = []
    results: list[dict[str, object]] = []
    for message, expected_choice in CASES:
        try:
            payload = post(message)
            routing = payload.get("routing") or {}
            answer = payload.get("answer") or {}
            choice = routing.get("choice")
            answer_status = answer.get("status")
            results.append({"message": message, "choice": choice, "answer_status": answer_status})
            print(f"{choice:6} {answer_status:9} {message}")
            if payload.get("status") != "routed" or choice != expected_choice:
                failures.append(f"{message}: expected {expected_choice}, got {choice}")
            if expected_choice == "solver" and answer_status != "solved":
                failures.append(f"{message}: solver did not return solved")
            if expected_choice == "ai" and answer_status != "answered":
                failures.append(f"{message}: AI did not return answered")
        except Exception as exc:
            results.append({"message": message, "error": str(exc)})
            failures.append(f"{message}: {exc}")
    evidence = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE_URL,
        "cases": results,
        "passed": not failures,
        "failures": failures,
    }
    evidence_path = Path("docs/evidence/demo-smoke-latest.json")
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if failures:
        print("\nFAILURES")
        print("\n".join(failures))
        return 1
    print("\nDEMO SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
