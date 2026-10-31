"""Project LLM-call and resource savings for a high-volume request scenario.

The model is intentionally explicit. Measured fixture values seed the exact
solver inputs, while LLM, energy, price, and traffic values remain assumptions.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Parameters:
    requests_per_month: int = 1_000_000
    months: int = 12
    solver_coverage: float = 0.85
    solver_success_rate: float = 1.0
    solver_wall_ms: float = 585.121
    solver_cpu_ms: float = 39.772
    solver_cpu_power_w: float = 65.0
    llm_latency_ms: float = 900.0
    llm_calls_per_request: float = 1.0
    llm_retry_rate: float = 0.05
    llm_success_rate: float = 0.95
    llm_input_tokens: int = 600
    llm_output_tokens: int = 150
    llm_gpu_seconds_per_call: float = 1.0
    llm_accelerator_power_w: float = 300.0
    pue: float = 1.2
    llm_input_price_per_1k: float = 0.003
    llm_output_price_per_1k: float = 0.015
    electricity_price_per_kwh: float = 0.12
    carbon_intensity_g_per_kwh: float = 400.0


def _finite(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"parameter must be finite: {value!r}")
    return float(value)


def _validate(parameters: Parameters) -> None:
    if parameters.requests_per_month < 1 or parameters.months < 1:
        raise ValueError("requests_per_month and months must be positive")
    for name in ("solver_coverage", "solver_success_rate", "llm_retry_rate", "llm_success_rate"):
        value = _finite(getattr(parameters, name))
        if not 0 <= value <= 1:
            raise ValueError(f"{name} must be between 0 and 1")
    for name in (
        "solver_wall_ms", "solver_cpu_ms", "solver_cpu_power_w", "llm_latency_ms",
        "llm_calls_per_request", "llm_input_tokens", "llm_output_tokens",
        "llm_gpu_seconds_per_call", "llm_accelerator_power_w", "pue",
        "electricity_price_per_kwh", "carbon_intensity_g_per_kwh",
    ):
        if _finite(getattr(parameters, name)) < 0:
            raise ValueError(f"{name} must be non-negative")
    if parameters.pue < 1:
        raise ValueError("pue must be at least 1")


def _energy_kwh(work_seconds: float, power_w: float, pue: float) -> float:
    return work_seconds * power_w / 3_600_000 * pue


def _scenario(name: str, requests: float, ai_requests: float, solver_requests: float, parameters: Parameters) -> dict[str, Any]:
    retry_multiplier = 1 + parameters.llm_retry_rate
    ai_calls = ai_requests * parameters.llm_calls_per_request * retry_multiplier
    input_tokens = ai_calls * parameters.llm_input_tokens
    output_tokens = ai_calls * parameters.llm_output_tokens
    total_tokens = input_tokens + output_tokens
    solver_cpu_hours = solver_requests * parameters.solver_cpu_ms / 1000 / 3600
    llm_gpu_hours = ai_calls * parameters.llm_gpu_seconds_per_call / 3600
    solver_energy_kwh = _energy_kwh(solver_requests * parameters.solver_cpu_ms / 1000, parameters.solver_cpu_power_w, parameters.pue)
    llm_energy_kwh = _energy_kwh(ai_calls * parameters.llm_gpu_seconds_per_call, parameters.llm_accelerator_power_w, parameters.pue)
    energy_kwh = solver_energy_kwh + llm_energy_kwh
    cost_usd = (input_tokens / 1000 * parameters.llm_input_price_per_1k) + (output_tokens / 1000 * parameters.llm_output_price_per_1k) + energy_kwh * parameters.electricity_price_per_kwh
    successful_tasks = solver_requests * parameters.solver_success_rate + ai_requests * parameters.llm_success_rate
    return {
        "name": name,
        "requests": requests,
        "solver_requests": solver_requests,
        "ai_requests": ai_requests,
        "ai_calls": ai_calls,
        "ai_calls_per_request": ai_calls / requests if requests else None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "total_tokens_millions": total_tokens / 1_000_000,
        "solver_cpu_hours": solver_cpu_hours,
        "llm_gpu_hours": llm_gpu_hours,
        "compute_hours": solver_cpu_hours + llm_gpu_hours,
        "solver_energy_kwh": solver_energy_kwh,
        "llm_energy_kwh": llm_energy_kwh,
        "energy_kwh": energy_kwh,
        "electricity_cost_usd": cost_usd,
        "carbon_kg": energy_kwh * parameters.carbon_intensity_g_per_kwh / 1000,
        "mean_latency_ms": (solver_requests * parameters.solver_wall_ms + ai_requests * parameters.llm_latency_ms) / requests if requests else None,
        "successful_tasks": successful_tasks,
        "success_rate": successful_tasks / requests if requests else None,
        "cost_per_success_usd": cost_usd / successful_tasks if successful_tasks else None,
    }


def project(parameters: Parameters | None = None) -> dict[str, Any]:
    parameters = parameters or Parameters()
    _validate(parameters)
    monthly = float(parameters.requests_per_month)
    annual = monthly * parameters.months
    solver_requests = monthly * parameters.solver_coverage
    ai_requests = monthly
    hybrid_ai_requests = monthly * (1 - parameters.solver_coverage)
    baseline = _scenario("AI only", monthly, ai_requests, 0, parameters)
    hybrid = _scenario("This app hybrid", monthly, hybrid_ai_requests, solver_requests, parameters)
    annual_baseline = _scenario("AI only", annual, annual, 0, parameters)
    annual_hybrid = _scenario("This app hybrid", annual, annual * (1 - parameters.solver_coverage), annual * parameters.solver_coverage, parameters)
    monthly_savings: dict[str, Any] = {}
    annual_savings: dict[str, Any] = {}
    for key in ("ai_calls", "total_tokens", "compute_hours", "energy_kwh", "electricity_cost_usd", "carbon_kg", "mean_latency_ms"):
        before = baseline[key]
        after = hybrid[key]
        monthly_savings[key] = {"absolute": before - after, "percent": (before - after) / before if before else None}
        before_annual = annual_baseline[key]
        after_annual = annual_hybrid[key]
        annual_savings[key] = {"absolute": before_annual - after_annual, "percent": (before_annual - after_annual) / before_annual if before_annual else None}
    assumptions = {
        "traffic": "Scenario assumption. One million requests per month for twelve months.",
        "solver_coverage": f"Measured fixture ratio. The exact route handled {parameters.solver_coverage:.0%} of the observations.",
        "solver_wall_ms": f"Measured fixture p50 end-to-end latency of {parameters.solver_wall_ms:.3f} ms.",
        "solver_cpu_ms": f"Measured fixture p50 solver worker time of {parameters.solver_cpu_ms:.3f} ms.",
        "llm_latency_ms": f"Scenario assumption. One {parameters.llm_latency_ms:.0f} ms model response before queueing.",
        "llm_tokens": f"Scenario assumption. {parameters.llm_input_tokens} input tokens plus {parameters.llm_output_tokens} output tokens per call.",
        "llm_retry_rate": f"Scenario assumption. {parameters.llm_retry_rate:.0%} extra calls for retries or transient failures.",
        "llm_energy": f"Scenario assumption. {parameters.llm_gpu_seconds_per_call:g} GPU-second at {parameters.llm_accelerator_power_w:g} W per model call, multiplied by PUE.",
        "electricity": f"Scenario assumption. {parameters.electricity_price_per_kwh:g} USD per kWh and {parameters.carbon_intensity_g_per_kwh:g} g CO2e per kWh.",
        "pricing": f"Scenario assumption. {parameters.llm_input_price_per_1k:g} USD per 1k input tokens and {parameters.llm_output_price_per_1k:g} USD per 1k output tokens.",
        "limitations": "This is a sensitivity model. It is not a measured provider energy or cost result.",
    }
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "parameters": asdict(parameters),
        "assumptions": assumptions,
        "monthly": {"baseline": baseline, "hybrid": hybrid},
        "annual": {"baseline": annual_baseline, "hybrid": annual_hybrid},
        "savings": annual_savings,
        "monthly_savings": monthly_savings,
        "annual_savings": annual_savings,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project theoretical AI-call and resource savings")
    parser.add_argument("--requests-per-month", type=int, default=Parameters.requests_per_month)
    parser.add_argument("--months", type=int, default=Parameters.months)
    parser.add_argument("--solver-coverage", type=float, default=Parameters.solver_coverage)
    parser.add_argument("--solver-wall-ms", type=float, default=Parameters.solver_wall_ms)
    parser.add_argument("--solver-cpu-ms", type=float, default=Parameters.solver_cpu_ms)
    parser.add_argument("--solver-cpu-power-w", type=float, default=Parameters.solver_cpu_power_w)
    parser.add_argument("--llm-latency-ms", type=float, default=Parameters.llm_latency_ms)
    parser.add_argument("--llm-retry-rate", type=float, default=Parameters.llm_retry_rate)
    parser.add_argument("--llm-success-rate", type=float, default=Parameters.llm_success_rate)
    parser.add_argument("--llm-input-tokens", type=int, default=Parameters.llm_input_tokens)
    parser.add_argument("--llm-output-tokens", type=int, default=Parameters.llm_output_tokens)
    parser.add_argument("--llm-gpu-seconds-per-call", type=float, default=Parameters.llm_gpu_seconds_per_call)
    parser.add_argument("--llm-accelerator-power-w", type=float, default=Parameters.llm_accelerator_power_w)
    parser.add_argument("--pue", type=float, default=Parameters.pue)
    parser.add_argument("--llm-input-price-per-1k", type=float, default=Parameters.llm_input_price_per_1k)
    parser.add_argument("--llm-output-price-per-1k", type=float, default=Parameters.llm_output_price_per_1k)
    parser.add_argument("--electricity-price-per-kwh", type=float, default=Parameters.electricity_price_per_kwh)
    parser.add_argument("--carbon-intensity-g-per-kwh", type=float, default=Parameters.carbon_intensity_g_per_kwh)
    parser.add_argument("--output", default="docs/evidence/theoretical-savings.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = Path(args.output)
    try:
        report = project(Parameters(
            requests_per_month=args.requests_per_month,
            months=args.months,
            solver_coverage=args.solver_coverage,
            solver_wall_ms=args.solver_wall_ms,
            solver_cpu_ms=args.solver_cpu_ms,
            solver_cpu_power_w=args.solver_cpu_power_w,
            llm_latency_ms=args.llm_latency_ms,
            llm_retry_rate=args.llm_retry_rate,
            llm_success_rate=args.llm_success_rate,
            llm_input_tokens=args.llm_input_tokens,
            llm_output_tokens=args.llm_output_tokens,
            llm_gpu_seconds_per_call=args.llm_gpu_seconds_per_call,
            llm_accelerator_power_w=args.llm_accelerator_power_w,
            pue=args.pue,
            llm_input_price_per_1k=args.llm_input_price_per_1k,
            llm_output_price_per_1k=args.llm_output_price_per_1k,
            electricity_price_per_kwh=args.electricity_price_per_kwh,
            carbon_intensity_g_per_kwh=args.carbon_intensity_g_per_kwh,
        ))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"theoretical benchmark failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report["savings"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
