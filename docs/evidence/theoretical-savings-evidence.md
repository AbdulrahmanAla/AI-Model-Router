# Concrete benchmark evidence

Generated from [the measured report](solver-five-runs.json) and [the theoretical report](theoretical-savings.json). The generator verifies the key values before writing this note.

## Measured evidence from the app

| Evidence | Value | Source field |
| --- | ---: | --- |
| Repeated runs | 5 | `repeats` |
| HTTP observations | 200 | `summary.solver.observations` |
| Supported-answer accuracy | 100.00% | `summary.solver.accuracy` |
| Passed scored tasks | 150 of 150 | `summary.solver.passed` and `scored_observations` |
| Boundary checks passed | 50 of 50 | `summary.solver.boundary_passed` and `boundary_observations` |
| Recorded model calls | 0 | `summary.solver.model_calls.known_total` |
| Median HTTP latency | 585.121 ms | `summary.solver.latency_ms.median` |
| Median solver worker time | 39.772 ms | `summary.solver.solver_ms.median` |
| Fixture SHA-256 | `EE15FF9C9E6733C99FB09B8BD96CF9E5746516059582AECD34EF4BC06D321DF2` | `environment.fixture_sha256` |
| Source commit | `5ec24e43221fe6148498467725e969ea9a665d75` | `environment.source_commit` |

This proves that the current exact route returned correct results on the frozen fixture without recorded model calls. It does not prove AI quality, provider latency, provider energy, or provider cost because no live AI baseline is present in this report.

## Theoretical inputs

| Parameter | Value | Evidence type |
| --- | ---: | --- |
| Requests per month | 1,000,000 | Scenario assumption |
| Solver coverage | 85.00% | Measured fixture ratio |
| Solver success rate | 100.00% | Measured scored fixture result |
| Solver wall time | 585.121 ms | Measured fixture p50 |
| Solver worker time | 39.772 ms | Measured fixture p50 |
| Model latency | 900 ms | Scenario assumption |
| Retry rate | 5.00% | Scenario assumption |
| Tokens per model call | 750 | Scenario assumption |
| GPU seconds per call | 1 s | Scenario assumption |
| Accelerator power | 300 W | Scenario assumption |
| PUE | 1.2 | Scenario assumption |
| Electricity price | $0.12 per kWh | Scenario assumption |
| Carbon intensity | 400 g CO2e per kWh | Scenario assumption |

## Annual calculation outputs

| Metric | AI only | This app hybrid | Difference | Reduction |
| --- | ---: | ---: | ---: | ---: |
| AI calls | 12,600,000 | 1,890,000 | 10,710,000 | 85.00% |
| Total tokens | 9,450,000,000 | 1,417,500,000 | 8,032,500,000 | 85.00% |
| Mean latency | 900 ms | 632.353 ms | 267.647 ms | 29.74% |
| Compute hours | 3,500 | 637.687 | 2,862.313 | 81.78% |
| Energy | 1,260 kWh | 197.79 kWh | 1,062.21 kWh | 84.30% |
| Token plus electricity cost | $51,181.2 | $7,678.235 | $43,502.965 | 85.00% |
| Carbon | 504 kg | 79.116 kg | 424.884 kg | 84.30% |
| Success rate | 95.00% | 99.25% | 4.25% points | n/a |

## What remains unmeasured

- No provider call log or provider usage response exists in the exact-route report.
- No live AI baseline exists for timing, token usage, or accuracy comparison.
- Energy, cost, carbon, GPU seconds, and PUE are scenario inputs rather than telemetry.
- The compute-hours row adds CPU hours and GPU hours as a directional workload proxy. It is not a hardware-equivalent unit.
- The latency row is a weighted mean-path estimate. It does not model queueing, batching, cache hits, or network congestion.

The conclusion is therefore conditional. The measured evidence proves the exact route's correctness and zero recorded model calls on the frozen fixture. The scale savings are calculated projections under the explicit parameters above.
