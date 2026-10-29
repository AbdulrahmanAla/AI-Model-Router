"""Run the frozen math cases against the public HTTP API.

The default command exercises only the exact route and makes no provider
calls. Use ``--live-ai`` explicitly for a configured provider comparison.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .scoring import score_ai_case, score_solver_case, summarize


DEFAULT_CASES = Path(__file__).with_name("cases.json")


def _request_json(base_url: str, path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "http_status": None,
            "body": None,
            "raw_body": "",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "transport_error": type(exc).__name__,
        }
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        decoded = None
    return {
        "http_status": status,
        "body": decoded if isinstance(decoded, dict) else None,
        "raw_body": raw.decode("utf-8", errors="replace")[:10000],
        "elapsed_ms": elapsed_ms,
        "transport_error": None,
    }


def _scenario_for_case(case: dict[str, Any], action: str) -> str:
    if action == "explain":
        return "explain"
    if action == "fallback":
        return "fallback"
    return "baseline"


def _run_one(case: dict[str, Any], base_url: str, timeout: float, action: str) -> dict[str, Any]:
    observation = _request_json(base_url, "/api/solve", case["request"], timeout)
    observation["score"] = score_solver_case(case, observation)
    observation["route"] = "solver"
    return observation


def _run_ai(case: dict[str, Any], base_url: str, timeout: float, action: str) -> dict[str, Any]:
    observation = _request_json(
        base_url,
        "/api/ai",
        {"action": _scenario_for_case(case, action), "request": case["request"]},
        timeout,
    )
    observation["score"] = score_ai_case(case, observation) if action in {"baseline", "fallback"} else {"passed": observation.get("http_status") == 200, "counted": False, "outcome": "explanation", "reason": "response recorded"}
    observation["route"] = "ai"
    observation["action"] = action
    return observation


def _load_cases(path: Path) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or len(cases) != 40:
        raise ValueError(f"expected 40 benchmark cases, found {len(cases) if isinstance(cases, list) else 'non-list'}")
    operation_counts: dict[str, int] = {}
    ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ValueError("each case needs a string id")
        if case["id"] in ids:
            raise ValueError(f"duplicate case id: {case['id']}")
        ids.add(case["id"])
        operation_counts[case["operation"]] = operation_counts.get(case["operation"], 0) + 1
    if operation_counts != {"derivative": 10, "integral": 10, "limit": 10, "equation": 10}:
        raise ValueError(f"expected ten cases per operation, found {operation_counts}")
    return cases


def _route_order(repeat: int, live_ai: bool) -> list[str]:
    if not live_ai:
        return ["solver"]
    return ["solver", "ai"] if repeat % 2 == 0 else ["ai", "solver"]


def _aggregate_case(case: dict[str, Any], solver_runs: list[dict[str, Any]], ai_runs: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    solver_scores = [run["score"] for run in solver_runs]
    result: dict[str, Any] = {
        "id": case["id"],
        "operation": case["operation"],
        "request": case["request"],
        "expected": case["expected"],
        "solver": {
            "runs": solver_runs,
            "summary": summarize(solver_runs, solver_scores),
        },
    }
    for action, runs in ai_runs.items():
        result[f"ai_{action}"] = {"runs": runs, "summary": summarize(runs, [run["score"] for run in runs])}
    return result


def _overall_summary(results: list[dict[str, Any]], route: str = "solver") -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    scores: list[dict[str, Any]] = []
    for result in results:
        section = result[route]
        observations.extend(section["runs"])
        scores.extend(run["score"] for run in section["runs"])
    report = summarize(observations, scores)
    expected_solved = sum(result["expected"]["status"] == "solved" for result in results)
    expected_unresolved = sum(result["expected"]["status"] == "unresolved" for result in results)
    expected_rejected = sum(result["expected"]["status"] == "rejected" for result in results)
    report["expected_cases"] = {"solved": expected_solved, "unresolved": expected_unresolved, "rejected": expected_rejected}
    report["claim_scope"] = "supported solved-case correctness and route metrics only"
    return report


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    cases = _load_cases(Path(args.cases))
    actions = [item.strip() for item in args.ai_actions.split(",") if item.strip()]
    allowed_actions = {"baseline", "explain", "fallback"}
    if any(action not in allowed_actions for action in actions):
        raise ValueError("--ai-actions accepts baseline, explain, and fallback")
    if not args.live_ai:
        actions = []
    case_runs: dict[str, dict[str, Any]] = {
        case["id"]: {"solver": [], "ai": {action: [] for action in actions}} for case in cases
    }
    for repeat in range(args.repeats):
        for route in _route_order(repeat, args.live_ai):
            for case in cases:
                if route == "solver":
                    case_runs[case["id"]]["solver"].append(_run_one(case, args.base_url, args.timeout, "solver"))
                else:
                    for action in actions:
                        # A baseline is matched across every case. Explain and fallback
                        # are explicit scenarios that can be selected for the same set.
                        case_runs[case["id"]]["ai"][action].append(_run_ai(case, args.base_url, args.timeout, action))
    results = []
    for case in cases:
        results.append(_aggregate_case(case, case_runs[case["id"]]["solver"], case_runs[case["id"]]["ai"]))
    summary: dict[str, Any] = {"solver": _overall_summary(results)}
    if args.live_ai:
        for action in actions:
            summary[f"ai_{action}"] = _overall_summary(results, f"ai_{action}")
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "repeats": args.repeats,
        "live_ai": bool(args.live_ai),
        "ai_actions": actions,
        "cases_file": str(Path(args.cases)),
        "summary": summary,
        "cases": results,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the AI Math Assistant evaluation cases")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--output", default="benchmark-results.json")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--live-ai", action="store_true", help="explicitly call the configured provider")
    parser.add_argument("--ai-actions", default="baseline", help="comma-separated baseline, explain, fallback")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.repeats < 1 or args.repeats > 20:
        print("--repeats must be between 1 and 20", file=sys.stderr)
        return 2
    try:
        report = run_benchmark(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        return 2
    output = Path(args.output)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
