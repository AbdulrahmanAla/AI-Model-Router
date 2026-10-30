from __future__ import annotations

import argparse

import pytest

from benchmarks.route_benchmark import (
    _ProcessSampler,
    _parse_pid_specs,
    _score,
    _summarize,
    _usage_records,
    run_routed_benchmark,
)


def _args(**overrides):
    values = {
        "base_url": "http://example.invalid",
        "cases": "benchmarks/cases.json",
        "case_id": [],
        "output": "ignored.json",
        "routes": "solver",
        "live_routes": False,
        "allow_paid_jev": False,
        "repeats": 1,
        "timeout": 1.0,
        "latency_budget_ms": None,
        "pid": [],
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_route_envelope_is_scored_at_the_existing_public_answer_boundary():
    from pathlib import Path
    import json

    cases = json.loads(Path("benchmarks/cases.json").read_text(encoding="utf-8"))
    case = next(item for item in cases if item["id"] == "derivative-01")
    observation = {
        "http_status": 200,
        "elapsed_ms": 12.0,
        "body": {
            "route": {"source": "jev", "choice": "solver"},
            "answer": {"status": "solved", "result": "2*x"},
            "metrics": {"route": "solver", "model_calls": 1},
        },
    }
    assert _score(case, "deterministic", observation, None)["passed"] is True


def test_jev_envelope_uses_solver_scorer_when_jev_selects_solver():
    import json
    from pathlib import Path

    case = next(item for item in json.loads(Path("benchmarks/cases.json").read_text()) if item["id"] == "derivative-01")
    observation = {
        "http_status": 200,
        "elapsed_ms": 12.0,
        "body": {
            "routing": {"choice": "solver", "attempts": [{"attempted": True, "provider": "jev", "model": "jev-1", "usage": {"prompt_tokens": 7, "total_tokens": 7}}]},
            "answer": {"status": "solved", "result": "2*x"},
        },
    }
    score = _score(case, "jev", observation, None)
    assert score["passed"] is True and score["counted"] is True
    assert _usage_records(observation)[0]["provider"] == "jev"


def test_jev_envelope_uses_ai_scorer_when_jev_selects_ai():
    import json
    from pathlib import Path

    case = next(item for item in json.loads(Path("benchmarks/cases.json").read_text()) if item["id"] == "derivative-01")
    observation = {
        "http_status": 200,
        "elapsed_ms": 12.0,
        "body": {
            "routing": {"choice": "ai", "attempts": [{"attempted": True, "provider": "jev", "model": "jev-1", "usage": {"prompt_tokens": 7, "total_tokens": 7}}, {"attempted": True, "provider": "ollama", "model": "qwen3.5:4b", "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}}]},
            "answer": {"status": "answered", "text": '{"status":"solved","result":"2*x"}'},
        },
    }
    score = _score(case, "jev", observation, None)
    assert score["passed"] is True and score["counted"] is True
    assert [record["provider"] for record in _usage_records(observation)] == ["jev", "ollama"]


def test_jev_failure_is_recorded_as_failed_without_inventing_usage():
    observation = {"http_status": 502, "body": {"error": "route_unavailable", "routing": {"attempts": [{"attempted": True, "provider": "jev", "model": "jev-1"}]}}}
    records = _usage_records(observation)
    assert records == [{"provider": "jev", "model": "jev-1", "model_calls": 1, "prompt_tokens": None, "completion_tokens": None, "total_tokens": None}]
    summary = _summarize([{"body": observation["body"], "elapsed_ms": 20.0, "score": {"passed": False, "counted": True, "deadline_failure": False}, "resources": {"total_cpu_seconds": 0.5, "peak_rss_bytes": 10}}], None)
    assert summary["provider_usage"]["jev:jev-1"]["total_tokens"]["unknown"] == 1
    assert summary["resource_totals"]["cpu_seconds"]["total"] == 0.5


def test_jev_aggregate_call_counter_is_used_when_attempt_details_are_omitted():
    observation = {"body": {"routing": {"jev_calls": 1, "model": "jev-1", "input_tokens": 3, "output_tokens": 2, "total_tokens": 5}}}
    assert _usage_records(observation) == [{"provider": "jev", "model": "jev-1", "model_calls": 1, "prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}]


def test_resource_cost_per_successful_task_includes_failed_attempt_costs():
    runs = [
        {"body": {"metrics": {"model_calls": 1, "total_tokens": 10}}, "elapsed_ms": 10.0, "score": {"passed": True, "counted": True, "deadline_failure": False}, "resources": {"total_cpu_seconds": 1.0, "peak_rss_bytes": 10}},
        {"body": {"metrics": {"model_calls": 1, "total_tokens": 20}}, "elapsed_ms": 20.0, "score": {"passed": False, "counted": True, "deadline_failure": False}, "resources": {"total_cpu_seconds": 2.0, "peak_rss_bytes": 20}},
    ]
    summary = _summarize(runs, None)
    assert summary["successful_tasks"] == 1
    assert summary["resource_totals"]["cpu_seconds"]["total"] == 3.0
    assert summary["resource_per_successful_task"]["cpu_seconds"] == 3.0
    assert summary["resource_totals"]["model_calls"]["total"] == 2.0


def test_latency_budget_turns_an_answer_into_a_deadline_failure():
    from pathlib import Path
    import json

    cases = json.loads(Path("benchmarks/cases.json").read_text(encoding="utf-8"))
    case = next(item for item in cases if item["id"] == "derivative-01")
    observation = {"http_status": 200, "elapsed_ms": 50.0, "body": {"status": "solved", "result": "2*x"}}
    score = _score(case, "solver", observation, 10.0)
    assert score["passed"] is False
    assert score["deadline_failure"] is True


def test_missing_provider_usage_stays_unknown_and_process_scope_is_explicit():
    assert _parse_pid_specs(["server=12", "ollama=13"]) == {"server": 12, "ollama": 13}
    sampler = _ProcessSampler({}, interval=0.001)
    sampler.start()
    result = sampler.stop()
    assert result["scope"] == "explicit local PIDs only"
    assert result["hosted_compute"] == "unknown"


def test_provider_routes_require_explicit_opt_in_and_paid_jev_opt_in():
    with pytest.raises(ValueError, match="live-routes"):
        run_routed_benchmark(_args(routes="deterministic"))
    with pytest.raises(ValueError, match="allow-paid-jev"):
        run_routed_benchmark(_args(routes="jev", live_routes=True))


def test_invalid_pid_spec_is_rejected():
    with pytest.raises(ValueError, match="role=PID"):
        _parse_pid_specs(["123"])


def test_routed_runs_alternate_route_order_and_keep_resource_scope(monkeypatch):
    case = {
        "id": "derivative-01",
        "operation": "derivative",
        "request": {"operation": "derivative", "expression": "x^2", "variable": "x"},
        "expected": {"status": "solved", "result": "2*x"},
    }
    order: list[str] = []

    def fake_load_cases(_path):
        return [case]

    def fake_route(_base_url, route, _case, _timeout, _sampler):
        order.append(route)
        if route == "solver":
            body = {"status": "solved", "result": "2*x", "metrics": {"model_calls": 0}}
        else:
            body = {"answer": {"status": "solved", "result": "2*x"}, "metrics": {"model_calls": 1}}
        return {"http_status": 200, "body": body, "elapsed_ms": 1.0}

    monkeypatch.setattr("benchmarks.route_benchmark._load_cases", fake_load_cases)
    monkeypatch.setattr("benchmarks.route_benchmark._route_observation", fake_route)
    report = run_routed_benchmark(_args(routes="solver,deterministic,ai_only", live_routes=True, repeats=2))
    assert order == ["solver", "deterministic", "ai_only", "ai_only", "deterministic", "solver"]
    assert report["summary"]["solver"]["task_success_rate"] == 1.0
    assert report["summary"]["deterministic"]["task_success_rate"] == 1.0
    assert report["resource_scope"].startswith("explicit local PIDs only")


def test_case_filter_selects_frozen_cases_without_changing_fixture_file(monkeypatch):
    cases = [
        {"id": "derivative-01", "operation": "derivative", "request": {"operation": "derivative", "expression": "x^2", "variable": "x"}, "expected": {"status": "solved", "result": "2*x"}},
        {"id": "derivative-02", "operation": "derivative", "request": {"operation": "derivative", "expression": "x^3", "variable": "x"}, "expected": {"status": "solved", "result": "3*x**2"}},
    ]
    monkeypatch.setattr("benchmarks.route_benchmark._load_cases", lambda _path: cases)
    monkeypatch.setattr("benchmarks.route_benchmark._route_observation", lambda *_args: {"http_status": 200, "body": {"status": "solved", "result": "2*x"}, "elapsed_ms": 1.0})
    report = run_routed_benchmark(_args(case_id=["derivative-01"]))
    assert report["case_filter"] == ["derivative-01"]
    assert [run["case_id"] for run in report["runs"]["solver"]] == ["derivative-01"]
