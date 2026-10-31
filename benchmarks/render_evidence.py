"""Build an auditable evidence note from measured and theoretical reports."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


def _pct(value: float) -> str:
    return f"{value:.2%}"


def _num(value: float, digits: int = 3) -> str:
    text = f"{value:,.{digits}f}"
    return text.rstrip("0").rstrip(".") if digits else text


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _verify(measured: dict[str, Any], theoretical: dict[str, Any]) -> None:
    summary = measured["summary"]["solver"]
    expected = {
        "observations": 200,
        "model_calls": 0.0,
        "accuracy": 1.0,
        "latency_median": 585.121,
        "solver_median": 39.772,
    }
    if summary["observations"] != expected["observations"]:
        raise ValueError("measured observation count changed")
    if summary["model_calls"]["known_total"] != expected["model_calls"]:
        raise ValueError("measured model call count changed")
    if not math.isclose(summary["accuracy"], expected["accuracy"], rel_tol=0, abs_tol=1e-12):
        raise ValueError("measured accuracy changed")
    if not math.isclose(summary["latency_ms"]["median"], expected["latency_median"], rel_tol=0, abs_tol=1e-9):
        raise ValueError("measured latency median changed")
    if not math.isclose(summary["solver_ms"]["median"], expected["solver_median"], rel_tol=0, abs_tol=1e-9):
        raise ValueError("measured solver median changed")
    annual = theoretical["annual"]
    savings = theoretical["annual_savings"]
    if not math.isclose(savings["ai_calls"]["percent"], 0.85, rel_tol=0, abs_tol=1e-12):
        raise ValueError("theoretical call reduction changed")
    if annual["hybrid"]["ai_calls"] >= annual["baseline"]["ai_calls"]:
        raise ValueError("hybrid scenario must use fewer AI calls")


def render(measured_path: Path, theoretical_path: Path) -> str:
    measured = _load(measured_path)
    theoretical = _load(theoretical_path)
    _verify(measured, theoretical)
    measured_summary = measured["summary"]["solver"]
    environment = measured.get("environment", {})
    params = theoretical["parameters"]
    baseline = theoretical["annual"]["baseline"]
    hybrid = theoretical["annual"]["hybrid"]
    savings = theoretical["annual_savings"]
    return f'''# Concrete benchmark evidence

Generated from [the measured report]({measured_path.as_posix()}) and [the theoretical report]({theoretical_path.as_posix()}). The generator verifies the key values before writing this note.

## Measured evidence from the app

| Evidence | Value | Source field |
| --- | ---: | --- |
| Repeated runs | {measured['repeats']} | `repeats` |
| HTTP observations | {measured_summary['observations']:,} | `summary.solver.observations` |
| Supported-answer accuracy | {_pct(measured_summary['accuracy'])} | `summary.solver.accuracy` |
| Passed scored tasks | {measured_summary['passed']:,} of {measured_summary['scored_observations']:,} | `summary.solver.passed` and `scored_observations` |
| Boundary checks passed | {measured_summary['boundary_passed']:,} of {measured_summary['boundary_observations']:,} | `summary.solver.boundary_passed` and `boundary_observations` |
| Recorded model calls | {_num(measured_summary['model_calls']['known_total'])} | `summary.solver.model_calls.known_total` |
| Median HTTP latency | {_num(measured_summary['latency_ms']['median'])} ms | `summary.solver.latency_ms.median` |
| Median solver worker time | {_num(measured_summary['solver_ms']['median'])} ms | `summary.solver.solver_ms.median` |
| Fixture SHA-256 | `{environment.get('fixture_sha256', 'not recorded')}` | `environment.fixture_sha256` |
| Source commit | `{environment.get('source_commit', 'not recorded')}` | `environment.source_commit` |

This proves that the current exact route returned correct results on the frozen fixture without recorded model calls. It does not prove AI quality, provider latency, provider energy, or provider cost because no live AI baseline is present in this report.

## Theoretical inputs

| Parameter | Value | Evidence type |
| --- | ---: | --- |
| Requests per month | {params['requests_per_month']:,} | Scenario assumption |
| Solver coverage | {_pct(params['solver_coverage'])} | Measured fixture ratio |
| Solver success rate | {_pct(params['solver_success_rate'])} | Measured scored fixture result |
| Solver wall time | {_num(params['solver_wall_ms'])} ms | Measured fixture p50 |
| Solver worker time | {_num(params['solver_cpu_ms'])} ms | Measured fixture p50 |
| Model latency | {_num(params['llm_latency_ms'])} ms | Scenario assumption |
| Retry rate | {_pct(params['llm_retry_rate'])} | Scenario assumption |
| Tokens per model call | {params['llm_input_tokens'] + params['llm_output_tokens']:,} | Scenario assumption |
| GPU seconds per call | {_num(params['llm_gpu_seconds_per_call'])} s | Scenario assumption |
| Accelerator power | {_num(params['llm_accelerator_power_w'])} W | Scenario assumption |
| PUE | {_num(params['pue'])} | Scenario assumption |
| Electricity price | ${_num(params['electricity_price_per_kwh'])} per kWh | Scenario assumption |
| Carbon intensity | {_num(params['carbon_intensity_g_per_kwh'])} g CO2e per kWh | Scenario assumption |

## Annual calculation outputs

| Metric | AI only | This app hybrid | Difference | Reduction |
| --- | ---: | ---: | ---: | ---: |
| AI calls | {_num(baseline['ai_calls'], 0)} | {_num(hybrid['ai_calls'], 0)} | {_num(savings['ai_calls']['absolute'], 0)} | {_pct(savings['ai_calls']['percent'])} |
| Total tokens | {_num(baseline['total_tokens'], 0)} | {_num(hybrid['total_tokens'], 0)} | {_num(savings['total_tokens']['absolute'], 0)} | {_pct(savings['total_tokens']['percent'])} |
| Mean latency | {_num(baseline['mean_latency_ms'])} ms | {_num(hybrid['mean_latency_ms'])} ms | {_num(savings['mean_latency_ms']['absolute'])} ms | {_pct(savings['mean_latency_ms']['percent'])} |
| Compute hours | {_num(baseline['compute_hours'])} | {_num(hybrid['compute_hours'])} | {_num(savings['compute_hours']['absolute'])} | {_pct(savings['compute_hours']['percent'])} |
| Energy | {_num(baseline['energy_kwh'])} kWh | {_num(hybrid['energy_kwh'])} kWh | {_num(savings['energy_kwh']['absolute'])} kWh | {_pct(savings['energy_kwh']['percent'])} |
| Token plus electricity cost | ${_num(baseline['electricity_cost_usd'])} | ${_num(hybrid['electricity_cost_usd'])} | ${_num(savings['electricity_cost_usd']['absolute'])} | {_pct(savings['electricity_cost_usd']['percent'])} |
| Carbon | {_num(baseline['carbon_kg'])} kg | {_num(hybrid['carbon_kg'])} kg | {_num(savings['carbon_kg']['absolute'])} kg | {_pct(savings['carbon_kg']['percent'])} |
| Success rate | {_pct(baseline['success_rate'])} | {_pct(hybrid['success_rate'])} | {_pct(hybrid['success_rate'] - baseline['success_rate'])} points | n/a |

## What remains unmeasured

- No provider call log or provider usage response exists in the exact-route report.
- No live AI baseline exists for timing, token usage, or accuracy comparison.
- Energy, cost, carbon, GPU seconds, and PUE are scenario inputs rather than telemetry.
- The compute-hours row adds CPU hours and GPU hours as a directional workload proxy. It is not a hardware-equivalent unit.
- The latency row is a weighted mean-path estimate. It does not model queueing, batching, cache hits, or network congestion.

The conclusion is therefore conditional. The measured evidence proves the exact route's correctness and zero recorded model calls on the frozen fixture. The scale savings are calculated projections under the explicit parameters above.
'''


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render concrete evidence for the theoretical savings model")
    parser.add_argument("--measured", default="docs/evidence/solver-five-runs.json")
    parser.add_argument("--theoretical", default="docs/evidence/theoretical-savings.json")
    parser.add_argument("--output", default="docs/evidence/theoretical-savings-evidence.md")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render(Path(args.measured), Path(args.theoretical)), encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"evidence render failed: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
