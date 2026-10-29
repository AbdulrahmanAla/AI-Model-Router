from __future__ import annotations

import argparse
import json
from pathlib import Path

import benchmarks.run_benchmark as runner
from benchmarks.scoring import (
    expressions_equivalent,
    roots_equivalent,
    score_ai_case,
    score_solver_case,
    summarize,
)


CASES = json.loads(Path("benchmarks/cases.json").read_text(encoding="utf-8"))


def test_fixture_set_has_ten_independent_cases_per_operation():
    assert len(CASES) == 40
    assert {operation: sum(case["operation"] == operation for case in CASES) for operation in {case["operation"] for case in CASES}} == {
        "derivative": 10,
        "integral": 10,
        "limit": 10,
        "equation": 10,
    }
    assert len({case["id"] for case in CASES}) == 40
    assert all(case.get("rationale") and case["expected"].get("status") for case in CASES)


def test_safe_result_scoring_accepts_equivalent_math_and_rejects_code():
    assert expressions_equivalent("tan(x)**2 + 1", "1 + tan(x)**2")
    from benchmarks.scoring import antiderivatives_equivalent
    assert antiderivatives_equivalent("(2*x + 1)**4/8", "2*x**4 + 4*x**3 + 3*x**2 + x")
    assert expressions_equivalent("sqrt(pi)*erf(x)/2", "sqrt(pi)*erf(x)/2")
    assert roots_equivalent(["2", "-2"], ["-2", "2"])
    assert roots_equivalent("{-2, 2}", ["-2", "2"])
    assert roots_equivalent("{}", [])
    assert not expressions_equivalent("__import__('os').system('whoami')", "0")
    assert not expressions_equivalent("(x**10000)**2", "x")


def test_safe_result_scoring_preserves_decimal_literal_text():
    assert expressions_equivalent("0.100000000000000001 - 0.1", "0.000000000000000001")
    assert not expressions_equivalent("1e-999", "0")


def test_solver_scoring_keeps_unresolved_and_rejected_out_of_accuracy():
    solved = next(case for case in CASES if case["id"] == "derivative-01")
    unresolved = next(case for case in CASES if case["id"] == "limit-07")
    rejected = next(case for case in CASES if case["id"] == "equation-10")
    solved_score = score_solver_case(solved, {"http_status": 200, "body": {"status": "solved", "result": "2*x"}})
    unresolved_score = score_solver_case(unresolved, {"http_status": 200, "body": {"status": "unresolved"}})
    rejected_score = score_solver_case(rejected, {"http_status": 422, "body": {"detail": "unknown variable"}})
    assert solved_score == {"passed": True, "counted": True, "outcome": "solved", "reason": "result matches"}
    assert unresolved_score["passed"] and not unresolved_score["counted"]
    assert rejected_score["passed"] and not rejected_score["counted"]


def test_scoring_accepts_empty_set_for_no_real_solutions():
    case = next(case for case in CASES if case["id"] == "equation-03")
    score = score_solver_case(case, {"http_status": 200, "body": {"status": "solved", "result": "{}"}})
    assert score["passed"] and score["counted"]


def test_bounded_input_accepts_safe_rejection_or_unresolved():
    case = next(case for case in CASES if case["id"] == "derivative-09")
    rejected = score_solver_case(case, {"http_status": 422, "body": {"detail": "power limit"}})
    unresolved = score_solver_case(case, {"http_status": 200, "body": {"status": "unresolved"}})
    assert rejected["passed"] and not rejected["counted"]
    assert unresolved["passed"] and not unresolved["counted"]


def test_ai_scoring_requires_machine_readable_answer_and_excludes_validation():
    solved = next(case for case in CASES if case["id"] == "derivative-01")
    rejected = next(case for case in CASES if case["id"] == "equation-10")
    valid = score_ai_case(solved, {"http_status": 200, "body": {"status": "answered", "text": '{"status":"solved","result":"2*x"}'}})
    prose = score_ai_case(solved, {"http_status": 200, "body": {"status": "answered", "text": "The answer is 2x."}})
    validation = score_ai_case(rejected, {"http_status": 422, "body": {"detail": "unknown variable"}})
    assert valid["passed"] and valid["counted"]
    assert not prose["passed"] and prose["outcome"] == "failure"
    assert validation["passed"] and not validation["counted"]
    deferred = next(case for case in CASES if case["id"] == "limit-07")
    review = score_ai_case(deferred, {"http_status": 200, "body": {"status": "answered", "text": '{"status":"solved","result":"0"}'}})
    assert review["outcome"] == "manual_review" and not review["counted"]


def test_ai_scoring_accepts_bounded_input_validation_rejection():
    case = next(case for case in CASES if case["id"] == "derivative-09")
    score = score_ai_case(case, {"http_status": 422, "body": {"detail": "power limit"}})
    assert score["passed"] and not score["counted"]


def test_summary_marks_missing_usage_as_unknown():
    observation = {"http_status": 200, "body": {"status": "solved", "metrics": {"solver_ms": 2.5}}, "elapsed_ms": 8.0}
    score = {"passed": True, "counted": True, "outcome": "solved", "reason": "result matches"}
    summary = summarize([observation], [score])
    assert summary["passed"] == 1
    assert summary["latency_ms"]["median"] == 8.0
    assert summary["token_usage"]["total_tokens"]["unknown"] == 1
    assert summary["model_calls"]["unknown"] == 1
    assert summary["token_usage"]["total_tokens"]["known_total"] == 0
    assert summary["token_usage"]["total_tokens"]["total"] is None
    assert summary["failed_outcomes"] == 0


def test_summary_counts_boundary_failures_separately():
    observation = {"http_status": 422, "body": {}}
    score = {"passed": False, "counted": False, "outcome": "rejected", "reason": "expected validation response"}
    summary = summarize([observation], [score])
    assert summary["failed_outcomes"] == 1
    assert summary["boundary_observations"] == 1
    assert summary["boundary_passed"] == 0


def test_runner_disables_ai_actions_without_explicit_live_flag(monkeypatch, tmp_path):
    calls: list[str] = []

    def fake_request(base_url, path, payload, timeout):
        calls.append(path)
        return {"http_status": 503, "body": {"status": "unresolved"}, "raw_body": "", "elapsed_ms": 1.0, "transport_error": None}

    monkeypatch.setattr(runner, "_request_json", fake_request)
    args = argparse.Namespace(
        cases="benchmarks/cases.json",
        base_url="http://example.invalid",
        output=str(tmp_path / "report.json"),
        repeats=1,
        timeout=0.1,
        live_ai=False,
        ai_actions="baseline,explain,fallback",
    )
    report = runner.run_benchmark(args)
    assert report["live_ai"] is False
    assert report["ai_actions"] == []
    assert all(path == "/api/solve" for path in calls)
    assert len(report["cases"]) == 40


def test_benchmark_cli_default_timeout_covers_provider_deadline():
    args = runner._parser().parse_args([])
    assert args.timeout == 60.0
