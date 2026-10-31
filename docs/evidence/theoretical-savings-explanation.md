# Theoretical savings model

This model asks one question. What happens if the exact solver handles the requests it can answer, while an AI-only system sends every request to a model?

The result is a scenario projection. It is not a measurement of a provider's energy use, price, or latency.

## The two scenarios

The AI-only scenario sends all 1,000,000 monthly requests to the model.

The hybrid scenario sends 85% of requests to the exact solver and 15% to the model. The 85% comes from the existing 200-observation fixture. The exact route handled 170 observations without a provider call. This is a route-coverage input, not a promise that every future workload has the same mix.

## Parameters

| Parameter | Value | Type | Reason |
| --- | ---: | --- | --- |
| Requests per month | 1,000,000 | Scenario assumption | Gives the result a large, readable operating scale. Results that count requests, calls, tokens, energy, and cost scale linearly with traffic. |
| Projection period | 12 months | Scenario assumption | Converts the monthly scenario into an annual presentation number. |
| Solver coverage | 85% | Measured fixture input | 170 of 200 fixture observations used the exact route without a provider. |
| Solver success rate | 100% | Measured fixture input | 150 of 150 scored solved observations passed. |
| Solver wall time | 585.121 ms | Measured fixture input | Median end-to-end time in the five-repeat report. |
| Solver worker time | 39.772 ms | Measured fixture input | Median exact solver time for scored solved observations. |
| Solver host power | 65 W | Scenario assumption | Approximate power for the local CPU process. |
| Model latency | 900 ms | Scenario assumption | One model response before queueing. |
| Model calls per request | 1.0 | Scenario assumption | One baseline completion per request. |
| Retry rate | 5% | Scenario assumption | Adds one extra call to 5% of requests. |
| Model success rate | 95% | Scenario assumption | Represents provider failures, invalid answers, or answers below the quality floor. |
| Input tokens per call | 600 | Scenario assumption | Represents the prompt and request context. |
| Output tokens per call | 150 | Scenario assumption | Represents the answer and structured response. |
| GPU seconds per call | 1.0 s | Scenario assumption | A simple model compute unit for comparing accelerator work. |
| Accelerator power | 300 W | Scenario assumption | Approximate power for the accelerator while serving the call. |
| PUE | 1.2 | Scenario assumption | Multiplies device energy by data-center overhead. |
| Input price | $0.003 per 1k tokens | Scenario assumption | Pricing knob for the model input side. |
| Output price | $0.015 per 1k tokens | Scenario assumption | Pricing knob for the model output side. |
| Electricity price | $0.12 per kWh | Scenario assumption | Converts energy into an electricity cost. It does not include provider margin or platform fees. |
| Carbon intensity | 400 g CO2e per kWh | Scenario assumption | Converts electricity into an illustrative carbon estimate. |

## Calculation order

The model applies the retry multiplier first.

```text
retry multiplier = 1 + retry rate
                 = 1 + 0.05
                 = 1.05
```

The AI-only scenario therefore makes 1.05 model calls per request.

```text
AI-only annual calls
= 12,000,000 requests × 1.05
= 12,600,000 calls
```

The hybrid scenario sends 15% of requests to the model.

```text
Hybrid annual AI requests
= 12,000,000 × (1 - 0.85)
= 1,800,000 requests

Hybrid annual calls
= 1,800,000 × 1.05
= 1,890,000 calls
```

The call reduction is therefore:

```text
(12,600,000 - 1,890,000) / 12,600,000
= 85%
```

Each model call uses 750 tokens.

```text
tokens per call = 600 input + 150 output = 750

AI-only annual tokens
= 12,600,000 × 750
= 9,450,000,000 tokens

Hybrid annual tokens
= 1,890,000 × 750
= 1,417,500,000 tokens
```

The hybrid mean-path latency is a weighted average. It assumes requests do not queue behind one another.

```text
hybrid latency
= (0.85 × 585.121 ms) + (0.15 × 900 ms)
= 632.353 ms
```

The model converts work into hours separately for the accelerator and the solver host.

```text
AI-only accelerator hours
= 12,600,000 GPU calls × 1 second / 3,600
= 3,500 GPU hours

Hybrid accelerator hours
= 1,890,000 × 1 / 3,600
= 525 GPU hours

Hybrid solver CPU hours
= 10,200,000 requests × 0.039772 seconds / 3,600
= 112.687 CPU hours
```

The chart reports the sum of those CPU and GPU hours as a simple compute-work proxy. CPU hours and GPU hours are different hardware resources, so this sum is directional rather than a physical equivalence.

Energy uses this conversion:

```text
energy in kWh = work seconds × power in watts × PUE / 3,600,000
```

For the AI-only case:

```text
12,600,000 seconds × 300 W × 1.2 / 3,600,000
= 1,260 kWh
```

For the hybrid case:

```text
model energy = 1,890,000 seconds × 300 W × 1.2 / 3,600,000
             = 189 kWh

solver energy = 10,200,000 × 0.039772 seconds × 65 W × 1.2 / 3,600,000
              = 8.790 kWh

total hybrid energy = 189 + 8.790
                    = 197.790 kWh
```

Cost combines token charges and electricity.

```text
cost = input tokens / 1,000 × input price
     + output tokens / 1,000 × output price
     + energy kWh × electricity price
```

The annual AI-only total is $51,181.20. The annual hybrid total is $7,678.23. The difference is $43,502.97 under these prices.

Carbon uses the selected grid intensity.

```text
carbon in kg = energy kWh × 400 grams / 1,000

AI-only = 1,260 × 400 / 1,000 = 504 kg CO2e
Hybrid  = 197.790 × 400 / 1,000 = 79.116 kg CO2e
```

The success-rate calculation uses the selected quality floors.

```text
AI-only success rate = 95%

Hybrid successful requests
= 10,200,000 solver requests × 100%
  + 1,800,000 AI requests × 95%
= 11,910,000 successful requests

Hybrid success rate
= 11,910,000 / 12,000,000
= 99.25%
```

## What the conclusion means

Under this scenario, the app's value comes from avoiding model work on requests that the exact solver can answer. The strongest conclusions are the call and token reductions because they follow directly from the 85% coverage assumption. The latency, energy, cost, and carbon conclusions depend on the selected model, power, retry, price, and traffic assumptions.

The model does not include queueing, batching, caching, network transfer, model warm-up, provider overhead outside the selected PUE, or changes in workload mix. Those effects can move the result in either direction. Change the command-line parameters before using the chart for a different workload or provider.

The JSON report stores the exact inputs and outputs. The generator is `benchmarks/theoretical_savings.py`.
