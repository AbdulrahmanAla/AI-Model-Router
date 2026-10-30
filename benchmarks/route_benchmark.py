"""Evaluate exact, routed, and AI-only workflows through public HTTP APIs.

This runner is opt-in for any provider route. The default command remains the
existing solver-only benchmark. Provider usage is preserved as unknown when a
response omits counters. CPU and memory measurements are scoped to explicitly
provided server or model PIDs and never describe hosted model compute.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from .run_benchmark import DEFAULT_CASES, _load_cases, _request_json
from .scoring import score_ai_case, score_solver_case


ROUTES = {"solver", "deterministic", "jev", "ai_only"}


def _numbers(values: Iterable[Any]) -> dict[str, Any]:
    values = list(values)
    numbers = [float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)]
    if not numbers:
        return {"count": 0, "median": None, "min": None, "max": None, "known_total": 0.0, "total": None if values else 0.0, "unknown": sum(value is None for value in values)}
    known = sum(numbers)
    return {
        "count": len(numbers),
        "median": median(numbers),
        "min": min(numbers),
        "max": max(numbers),
        "known_total": known,
        "total": known if len(numbers) == len(values) else None,
        "unknown": sum(value is None for value in values),
    }


def _parse_pid_specs(specs: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for spec in specs:
        if "=" not in spec:
            raise ValueError(f"--pid expects role=PID, got {spec!r}")
        role, value = spec.split("=", 1)
        role = role.strip().lower()
        try:
            pid = int(value)
        except ValueError as exc:
            raise ValueError(f"invalid PID in {spec!r}") from exc
        if not role or pid <= 0:
            raise ValueError(f"invalid process scope {spec!r}")
        result[role] = pid
    return result


class _ProcessSampler:
    """Sample explicitly scoped local processes, when psutil is installed."""

    def __init__(self, pids: dict[str, int], interval: float = 0.05):
        self.pids = pids
        self.interval = interval
        self.samples: dict[str, dict[str, float | int | None]] = {}
        self.process_status: dict[str, str] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._psutil: Any = None
        try:
            import psutil  # type: ignore

            self._psutil = psutil
        except ImportError:
            self.error = "psutil is not installed"
        else:
            self.error = None

    def _read(self, pid: int) -> tuple[float | None, int | None, str]:
        if self._psutil is None:
            return None, None, "psutil_unavailable"
        try:
            process = self._psutil.Process(pid)
            cpu = process.cpu_times()
            return float(cpu.user + cpu.system), int(process.memory_info().rss), "observed"
        except self._psutil.NoSuchProcess:
            return None, None, "process_exited_or_pid_reused"
        except self._psutil.AccessDenied:
            return None, None, "access_denied"
        except (self._psutil.Error, OSError, ValueError):
            return None, None, "read_error"

    def _sample(self) -> None:
        for role, pid in self.pids.items():
            cpu, rss, status = self._read(pid)
            self.process_status[role] = status
            current = self.samples.setdefault(role, {"cpu_seconds": None, "peak_rss_bytes": None, "initial_cpu_seconds": None})
            if cpu is not None:
                if current["initial_cpu_seconds"] is None:
                    current["initial_cpu_seconds"] = cpu
                current["cpu_seconds"] = max(0.0, cpu - float(current["initial_cpu_seconds"]))
            if rss is not None:
                current["peak_rss_bytes"] = max(int(current["peak_rss_bytes"] or 0), rss)

    def start(self) -> None:
        self._sample()
        if self._psutil is None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self._sample()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        self._sample()
        return {
            "scope": "explicit local PIDs only",
            "processes": self.samples,
            "process_status": self.process_status,
            "unavailable": self.error,
            "subprocesses": "excluded unless their PIDs are supplied explicitly",
            "hosted_compute": "unknown",
            "gpu_compute": "not measured by CPU time",
        }


def _unwrap_observation(observation: dict[str, Any]) -> dict[str, Any]:
    """Expose an answer envelope to the existing safe scorers."""
    body = observation.get("body")
    if not isinstance(body, dict):
        return observation
    answer = body.get("answer")
    if not isinstance(answer, dict):
        return observation
    merged = dict(observation)
    answer_body = dict(answer)
    if "metrics" not in answer_body and isinstance(body.get("metrics"), dict):
        answer_body["metrics"] = body["metrics"]
    merged["body"] = answer_body
    return merged


def _body_metrics(observation: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    body = observation.get("body")
    if not isinstance(body, dict):
        return {}, {}
    answer = body.get("answer")
    answer_body = answer if isinstance(answer, dict) else body
    routing = body.get("routing")
    routing = routing if isinstance(routing, dict) else {}
    metrics = answer_body.get("metrics")
    if not isinstance(metrics, dict):
        metrics = body.get("metrics")
    if not isinstance(metrics, dict):
        metrics = routing.get("metrics")
    return answer_body, metrics if isinstance(metrics, dict) else {}


def _route_observation(base_url: str, route: str, case: dict[str, Any], timeout: float, sampler: _ProcessSampler) -> dict[str, Any]:
    if route == "solver":
        return _request_json(base_url, "/api/solve", case["request"], timeout)
    payload = {"mode": route, "request": case["request"]}
    return _request_json(base_url, "/api/route", payload, timeout)


def _score(case: dict[str, Any], route: str, observation: dict[str, Any], latency_budget_ms: float | None) -> dict[str, Any]:
    normalized = _unwrap_observation(observation)
    answer_body, _ = _body_metrics(observation)
    is_ai_answer = answer_body.get("status") == "answered" or isinstance(answer_body.get("text"), str)
    if not is_ai_answer:
        score = score_solver_case(case, normalized)
    else:
        score = score_ai_case(case, normalized)
    elapsed = observation.get("elapsed_ms")
    if score.get("passed") is True and score.get("counted") and latency_budget_ms is not None and isinstance(elapsed, (int, float)) and elapsed > latency_budget_ms:
        return {**score, "passed": False, "deadline_failure": True, "reason": f"latency budget exceeded: {elapsed:.3f} ms > {latency_budget_ms:.3f} ms"}
    return {**score, "deadline_failure": False}


def _usage_records(observation: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract one record per attempted provider/model call.

    Router responses keep attempts under ``routing.attempts``. Missing usage
    remains null on that attempt, rather than being filled from an aggregate.
    """
    body = observation.get("body")
    if not isinstance(body, dict):
        return []
    _, metrics = _body_metrics(observation)
    routing = body.get("routing") if isinstance(body.get("routing"), dict) else {}
    attempts = routing.get("attempts") or body.get("attempts")
    if not isinstance(attempts, list):
        attempts = []
    records: list[dict[str, Any]] = []
    for attempt in attempts:
        if not isinstance(attempt, dict) or not attempt.get("attempted"):
            continue
        attempt_metrics = attempt.get("metrics") if isinstance(attempt.get("metrics"), dict) else {}
        usage = attempt.get("usage") if isinstance(attempt.get("usage"), dict) else {}
        if not usage:
            usage = attempt_metrics
        records.append({
            "provider": str(attempt.get("provider") or attempt.get("route") or "unknown"),
            "model": attempt.get("model") or attempt_metrics.get("model"),
            "model_calls": attempt.get("model_calls", attempt.get("ai_calls", 1)),
            "prompt_tokens": usage.get("prompt_tokens", usage.get("input_tokens")),
            "completion_tokens": usage.get("completion_tokens", usage.get("output_tokens")),
            "total_tokens": usage.get("total_tokens"),
        })
    if records:
        return records
    calls = metrics.get("model_calls", metrics.get("ai_calls"))
    if isinstance(calls, int) and calls > 0:
        return [{
            "provider": str(metrics.get("provider") or metrics.get("route") or "unknown"),
            "model": metrics.get("model"),
            "model_calls": calls,
            "prompt_tokens": metrics.get("prompt_tokens", metrics.get("input_tokens")),
            "completion_tokens": metrics.get("completion_tokens", metrics.get("output_tokens")),
            "total_tokens": metrics.get("total_tokens"),
        }]
    return []


def _route_metrics(observation: dict[str, Any]) -> dict[str, Any]:
    _, metrics = _body_metrics(observation)
    records = _usage_records(observation)
    provider_calls: Counter[str] = Counter()
    for record in records:
        calls = record.get("model_calls")
        if isinstance(calls, int) and calls >= 0:
            provider_calls[str(record["provider"])] += calls
    return {"provider_calls": dict(provider_calls), "records": records, "model": metrics.get("model"), "route": metrics.get("route")}


def _summarize(runs: list[dict[str, Any]], latency_budget_ms: float | None) -> dict[str, Any]:
    scores = [run["score"] for run in runs]
    counted = [score for score in scores if score.get("counted")]
    passed = sum(score.get("passed") is True for score in scores)
    metric_values: list[dict[str, Any]] = []
    provider_calls: Counter[str] = Counter()
    provider_usage: dict[str, dict[str, list[Any]]] = {}
    models: set[str] = set()
    for run in runs:
        _, metrics = _body_metrics(run)
        records = _usage_records(run)
        calls = sum(record["model_calls"] for record in records if isinstance(record.get("model_calls"), int)) if records else metrics.get("model_calls", metrics.get("ai_calls"))
        metric_values.append({
            "elapsed_ms": run.get("elapsed_ms"),
            "model_calls": calls,
            "prompt_tokens": sum(record["prompt_tokens"] for record in records if isinstance(record.get("prompt_tokens"), int)) if records and all(isinstance(record.get("prompt_tokens"), int) for record in records) else (None if records else metrics.get("prompt_tokens", metrics.get("input_tokens"))),
            "completion_tokens": sum(record["completion_tokens"] for record in records if isinstance(record.get("completion_tokens"), int)) if records and all(isinstance(record.get("completion_tokens"), int) for record in records) else (None if records else metrics.get("completion_tokens", metrics.get("output_tokens"))),
            "total_tokens": sum(record["total_tokens"] for record in records if isinstance(record.get("total_tokens"), int)) if records and all(isinstance(record.get("total_tokens"), int) for record in records) else (None if records else metrics.get("total_tokens")),
            "cpu_seconds": (run.get("resources") or {}).get("total_cpu_seconds"),
            "peak_rss_bytes": (run.get("resources") or {}).get("peak_rss_bytes"),
        })
        for key, value in _route_metrics(run).get("provider_calls", {}).items():
            provider_calls[key] += value
        model = _route_metrics(run).get("model")
        if isinstance(model, str):
            models.add(model)
        for record in records:
            key = f"{record['provider']}:{record.get('model') or 'unknown'}"
            bucket = provider_usage.setdefault(key, {name: [] for name in ("model_calls", "prompt_tokens", "completion_tokens", "total_tokens")})
            for name in bucket:
                bucket[name].append(record.get(name))
    resource_totals = {
        "model_calls": _numbers([item["model_calls"] for item in metric_values]),
        "total_tokens": _numbers([item["total_tokens"] for item in metric_values]),
        "cpu_seconds": _numbers([item["cpu_seconds"] for item in metric_values]),
    }
    resource_per_success = {
        name: (values["total"] / passed if values["total"] is not None and passed else None)
        for name, values in resource_totals.items()
    }
    return {
        "observations": len(runs),
        "successful_tasks": passed,
        "task_success_rate": passed / len(runs) if runs else None,
        "scored_observations": len(counted),
        "accuracy": sum(score.get("passed") is True for score in counted) / len(counted) if counted else None,
        "failed_outcomes": sum(score.get("passed") is False for score in scores),
        "deadline_failures": sum(score.get("deadline_failure") for score in scores),
        "latency_budget_ms": latency_budget_ms,
        "latency_ms": _numbers([item["elapsed_ms"] for item in metric_values]),
        "model_calls": _numbers([item["model_calls"] for item in metric_values]),
        "token_usage": {name: _numbers([item[name] for item in metric_values]) for name in ("prompt_tokens", "completion_tokens", "total_tokens")},
        "local_cpu_seconds": _numbers([item["cpu_seconds"] for item in metric_values]),
        "peak_rss_bytes": _numbers([item["peak_rss_bytes"] for item in metric_values]),
        "resource_totals": resource_totals,
        "resource_per_successful_task": resource_per_success,
        "provider_calls": dict(provider_calls),
        "provider_usage": {key: {name: _numbers(values) for name, values in metrics.items()} for key, metrics in provider_usage.items()},
        "models": sorted(models),
        "explanation_quality": "manual rubric required; response shape is not a quality score",
    }


def run_routed_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    cases = _load_cases(Path(args.cases))
    if args.case_id:
        wanted = set(args.case_id)
        available = {case["id"] for case in cases}
        missing = sorted(wanted - available)
        if missing:
            raise ValueError(f"unknown --case-id value(s): {', '.join(missing)}")
        cases = [case for case in cases if case["id"] in wanted]
        if not cases:
            raise ValueError("--case-id must select at least one case")
    routes = [item.strip() for item in args.routes.split(",") if item.strip()]
    if not routes or any(route not in ROUTES for route in routes):
        raise ValueError(f"--routes accepts comma-separated values from {sorted(ROUTES)}")
    if any(route != "solver" for route in routes) and not args.live_routes:
        raise ValueError("provider routes require --live-routes")
    if "jev" in routes and not args.allow_paid_jev:
        raise ValueError("jev route requires explicit --allow-paid-jev")
    pid_specs = _parse_pid_specs(args.pid)
    runs: dict[str, list[dict[str, Any]]] = {route: [] for route in routes}
    for repeat in range(args.repeats):
        ordered = routes if repeat % 2 == 0 else list(reversed(routes))
        for route in ordered:
            for case in cases:
                sampler = _ProcessSampler(pid_specs)
                sampler.start()
                observation = _route_observation(args.base_url, route, case, args.timeout, sampler)
                resources = sampler.stop()
                processes = resources.get("processes", {})
                cpu_values = [item.get("cpu_seconds") for item in processes.values() if isinstance(item, dict)]
                rss_values = [item.get("peak_rss_bytes") for item in processes.values() if isinstance(item, dict)]
                resources["total_cpu_seconds"] = sum(value for value in cpu_values if isinstance(value, (int, float))) if cpu_values and all(value is not None for value in cpu_values) else None
                resources["peak_rss_bytes"] = max((value for value in rss_values if isinstance(value, int)), default=None)
                observation["route"] = route
                observation["repeat"] = repeat
                observation["measurement_state"] = "first-run" if repeat == 0 else "subsequent-run"
                observation["resources"] = resources
                observation["score"] = _score(case, route, observation, args.latency_budget_ms)
                observation["case_id"] = case["id"]
                runs[route].append(observation)
    return {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "cases_file": str(Path(args.cases)),
        "case_filter": args.case_id,
        "routes": routes,
        "repeats": args.repeats,
        "live_routes": bool(args.live_routes),
        "paid_jev_allowed": bool(args.allow_paid_jev),
        "latency_budget_ms": args.latency_budget_ms,
        "resource_scope": "explicit local PIDs only; hosted CPU/GPU unknown; GPU not measured by CPU time",
        "pid_scope": pid_specs,
        "summary": {route: _summarize(route_runs, args.latency_budget_ms) for route, route_runs in runs.items()},
        "runs": runs,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare exact, routed, and AI-only public HTTP workflows")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--case-id", action="append", default=[], help="select a frozen case for a quick provider iteration; repeat this option")
    parser.add_argument("--output", default="routed-benchmark-results.json")
    parser.add_argument("--routes", default="solver", help="comma-separated solver, deterministic, jev, ai_only")
    parser.add_argument("--live-routes", action="store_true", help="explicitly enable provider and route requests")
    parser.add_argument("--allow-paid-jev", action="store_true", help="explicitly allow Jev route calls")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--latency-budget-ms", type=float, default=None)
    parser.add_argument("--pid", action="append", default=[], help="explicit local process scope role=PID; repeat for server and model")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.repeats < 1 or args.repeats > 20:
        print("--repeats must be between 1 and 20", file=sys.stderr)
        return 2
    if args.latency_budget_ms is not None and args.latency_budget_ms <= 0:
        print("--latency-budget-ms must be positive", file=sys.stderr)
        return 2
    try:
        report = run_routed_benchmark(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"routed benchmark failed: {exc}", file=sys.stderr)
        return 2
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
