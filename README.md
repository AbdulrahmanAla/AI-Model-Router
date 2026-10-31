# Model Router

Model Router is a chat-style math website for derivatives, integrals, limits, simple real polynomial equations, and bounded natural-language prompts. It recognizes supported math, converts it into a validated structured request, solves it with SymPy, and shows the result with steps and a check status.

The exact solver is the default path. It does not need a general-purpose language model. Optional AI actions can explain an exact result, answer a request that needs language generation, or provide a fallback for work outside the exact solver's boundary.

The project also includes an optional Jev route. Jev makes a small route decision before the application chooses the exact solver, an AI model, or a refusal. The decision is recorded next to the answer so you can see why a route was selected and how many model calls it used.

## What the project does

- Solves supported derivatives, integrals, limits, and real polynomial equations with SymPy.
- Checks results with symbolic checks, substitutions, numerical samples, or numerical quadrature when the operation allows it.
- Returns `unresolved` when a request is valid but outside the safe supported boundary or the solver deadline.
- Validates the input grammar and rejects unsafe or malformed requests before expensive work.
- Provides optional AI explanations that are grounded in an exact result. AI prose remains unverified.
- Accepts an optional plain-language prompt through the AI route. A prompt is never passed to SymPy as executable math.
- Recognizes a small set of phrases such as "differentiate x^2" and "integrate x from 0 to 1". Unknown messages stay at the language-model boundary.
- Records route choice, model calls, token counts, latency, fallback reasons, and missing usage as unknown instead of zero.

## Why use a decision classifier?

A general language model can answer many kinds of requests, but it is expensive to call for every request. A decision classifier handles a narrower job. It reads the request and predicts one label from a small set such as `solver`, `ai`, or `refuse`.

Because it only chooses a route, a decision classifier can be much smaller than a model that generates a full answer. It returns a label and optional confidence or probabilities instead of a long response. That means less output, less work per decision, and a smaller compute cost than using a general model for every task.

The classifier helps reduce general AI use when it sends structured math to the exact solver. The exact solver can answer those requests with zero general-model calls. The Jev route itself makes one routing call when it is enabled, so the total saving depends on how many expensive answer-generation calls it avoids. The benchmark must measure that trade-off for the target workload.

## What Jev is in this project

Jev is a server-side decision model used as a route classifier. The application asks Jev to choose one typed result:

- `solver`: use the bounded SymPy solver for a validated structured math request.
- `ai`: use the configured AI provider for language work or a request that needs generation.
- `refuse`: stop when the request is unsafe, malformed, or outside the allowed input size.

Jev chooses a route. It does not calculate the mathematical answer and it cannot change an exact result. If Jev is missing, times out, or returns malformed data, the server falls back to the deterministic classification and records the failed attempt. A structured request still reaches the exact solver when that fallback is `solver`.

The Jev adapter uses `TYPESAFE_API_KEY`, `JEV_BASE_URL`, `JEV_MODEL`, and `JEV_TIMEOUT_SECONDS`. Credentials stay on the server. The default Jev endpoint and model can be overridden with environment variables.

## How a request moves through the project

```text
Browser
|
+-- Chat mode: POST /api/chat
|   |
|   +-- Parse only the supported free-form math phrases
|   +-- Validate extracted math with the same schema and grammar as /api/solve
|   +-- Keep unknown messages as language prompts
|
+-- Structured route: POST /api/route
|   |
|   +-- Accept one structured request or one plain-language prompt
|   +-- deterministic
|   |   +-- Structured request -> exact SymPy solver
|   |   `-- Plain-language prompt -> configured AI provider
|   +-- jev
|   |   +-- Jev decision classifier -> solver, ai, or refuse
|   |   +-- Jev unavailable -> deterministic fallback
|   |   +-- solver -> exact SymPy result
|   |   +-- ai -> configured AI provider
|   |   `-- refuse -> explicit refusal with routing evidence
|   `-- ai_only -> configured AI provider
|
`-- Exact mode: POST /api/solve
    +-- Validate the request schema and bounded expression grammar
    +-- Run the SymPy solver in a bounded worker
    `-- Check the result and return steps, notes, and metrics
```

The main code is organized around these units:

```text
AI-Math-Assistant/
|-- app/
|   |-- main.py       # FastAPI endpoints and request validation
|   |-- chat.py        # Conservative free-form math extraction
|   |-- solver.py     # Bounded SymPy calculations and checks
|   |-- router.py     # Jev and deterministic route selection
|   `-- ai.py         # Optional hosted or local AI providers
|-- web/
|   |-- index.html    # Chat interface and route selector
|   `-- app.js        # Browser requests, results, and route evidence
|-- benchmarks/
|   |-- cases.json    # 40 frozen cases, ten per operation
|   |-- run_benchmark.py
|   `-- route_benchmark.py
|-- tests/            # API, router, benchmark, and browser contract tests
`-- docs/
    |-- routing-spec.md
    |-- evaluation.md
    `-- deploy.md
```

## Run it locally

Python 3.14 is the tested runtime. Node.js is used for JavaScript syntax and frontend behavior checks.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c requirements.lock -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [Model Router locally](http://127.0.0.1:8000). Write a question in the chat composer and submit it. You can enter a formula such as `x^3*sin(x)` or a supported phrase such as `find the derivative of x^2`. The visual editor supports fractions, exponents, roots, trigonometric functions, and symbols. Typed input uses explicit multiplication such as `2*x`.

The route selector offers the exact solver, deterministic routing, Jev routing, and AI-only comparison. Exact math works without any provider configuration.

## Configure optional AI and Jev providers

For a hosted OpenAI-compatible provider, set `AI_BASE_URL`, `AI_MODEL`, and `AI_API_KEY`. The adapter appends `/chat/completions` to the base URL.

For a local Ollama provider, set the provider and model:

```powershell
$env:AI_PROVIDER = "ollama"
$env:OLLAMA_MODEL = "qwen3.5:4b"
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_TIMEOUT_SECONDS = "120"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

For Jev routing, set `TYPESAFE_API_KEY`. You can also set `JEV_BASE_URL`, `JEV_MODEL`, and `JEV_TIMEOUT_SECONDS`. The Jev route is optional. If it is not configured, the server uses the deterministic route and reports that fallback.

Keep `.env` and all provider keys out of Git. See [provider research](docs/research/provider.md), [the routing specification](docs/routing-spec.md), and [the deployment guide](docs/deploy.md) for configuration limits.

## Check the project

Run the local verification gate before merging:

```powershell
.\.venv\Scripts\python.exe scripts/check.py
```

The gate runs public API tests, router tests, JavaScript checks, frontend behavior tests, and real HTTP checks against the 40 frozen math cases. Provider contract tests use fake transports and do not make paid calls.

## Latest benchmark results

### Measured exact-route run

The latest report ran the public HTTP API five times over the frozen 40-case fixture. That produced 200 observations on one Uvicorn process with no provider configured.

| Metric | Result | Evidence |
| --- | ---: | --- |
| Supported-answer accuracy | 150/150, 100% | `summary.solver.passed` and `scored_observations` |
| Boundary handling | 50/50 passed | `summary.solver.boundary_passed` and `boundary_observations` |
| Recorded model calls | 0 across 200 observations | `summary.solver.model_calls.known_total` |
| End-to-end latency | 585.121 ms p50, 515.202 to 1,278.825 ms | `summary.solver.latency_ms` |
| Solver worker time | 39.772 ms p50 | `summary.solver.solver_ms.median` |
| Known solver work | 7,693.593 ms across scored solved observations | `summary.solver.solver_ms.known_total` |

The 150 scored observations are the 30 supported solved cases repeated five times. The other 50 observations cover unresolved, rejected, and safely bounded inputs. This is evidence for exact-route correctness and recorded zero-call behavior on the frozen fixture. It is not an AI quality, provider latency, energy, or cost comparison.

- [Raw measured report](docs/evidence/solver-five-runs.json)
- [Measured benchmark dashboard](docs/evidence/measured-benchmark.html)
- [Measured benchmark slide](docs/evidence/compute-benchmark-slide.svg)

![Measured exact-route benchmark](docs/evidence/compute-benchmark-slide.png)

The purple AI baseline bars remain empty because no live provider report was supplied. Provider token usage is therefore unknown, not zero.

### Scenario projection at one million requests per month

The scale model compares an AI-only workload with a hybrid workload. The hybrid sends 85% of requests to the exact solver and 15% to a model. The 85% comes from the measured fixture ratio, 170 exact-route observations out of 200. The remaining traffic, model behavior, energy, price, and carbon values are assumptions.

| Annual metric | AI only | This app hybrid | Difference | Reduction |
| --- | ---: | ---: | ---: | ---: |
| AI calls | 12,600,000 | 1,890,000 | 10,710,000 | 85.00% |
| Total tokens | 9,450,000,000 | 1,417,500,000 | 8,032,500,000 | 85.00% |
| Mean request latency | 900 ms | 632.353 ms | 267.647 ms | 29.74% |
| Compute work proxy | 3,500 h | 637.687 h | 2,862.313 h | 81.78% |
| Energy | 1,260 kWh | 197.790 kWh | 1,062.210 kWh | 84.30% |
| Token plus electricity cost | $51,181.20 | $7,678.23 | $43,502.97 | 85.00% |
| Carbon estimate | 504 kg CO2e | 79.116 kg CO2e | 424.884 kg CO2e | 84.30% |
| Success rate | 95.00% | 99.25% | 4.25 points | n/a |

These are calculated projections. They are not measurements from an AI provider. The compute row adds solver CPU hours and model GPU hours as a directional work proxy, so the two hardware resources are not physically equivalent.

- [Theoretical savings report](docs/evidence/theoretical-savings.json)
- [Assumptions and calculation steps](docs/evidence/theoretical-savings-explanation.md)
- [Evidence note with source fields](docs/evidence/theoretical-savings-evidence.md)
- [Theoretical savings slide](docs/evidence/theoretical-savings.svg)

![Scenario projection for one million monthly requests](docs/evidence/theoretical-savings.png)

The chart is labeled as illustrative because model latency, retries, token counts, accelerator power, PUE, prices, electricity, and carbon intensity are scenario inputs.

Regenerate the scenario report and its evidence note with the committed benchmark tools:

```text
python -m benchmarks.theoretical_savings --output docs/evidence/theoretical-savings.json
python -m benchmarks.render_evidence --output docs/evidence/theoretical-savings-evidence.md
python -m benchmarks.render_theoretical docs/evidence/theoretical-savings.json --output docs/evidence/theoretical-savings.svg --png docs/evidence/theoretical-savings.png
```

### Assumptions and their evidence

| Assumption or input | Value | Type | Evidence or limitation |
| --- | ---: | --- | --- |
| Monthly traffic | 1,000,000 requests | Scenario assumption | A presentation scale. It is not production traffic telemetry. |
| Projection period | 12 months | Scenario assumption | Converts monthly values to annual values. |
| Solver coverage | 85% | Measured fixture input | 170 of 200 observations used the exact route without a provider call. |
| Solver success rate | 100% | Measured fixture input | 150 of 150 scored solved observations passed. |
| Solver wall time | 585.121 ms p50 | Measured fixture input | Five repeats on the public HTTP route. |
| Solver worker time | 39.772 ms p50 | Measured fixture input | Reported separately from end-to-end HTTP time. |
| Model latency | 900 ms | Scenario assumption | One response before queueing. No live model baseline was measured. |
| Retry rate | 5% | Scenario assumption | Adds an average 0.05 model calls per model-routed request. |
| Model success rate | 95% | Scenario assumption | A selected quality floor for the projection. |
| Tokens per model call | 600 input plus 150 output | Scenario assumption | 750 tokens per call. Provider usage is absent from the exact-route report. |
| Model compute | 1 GPU-second at 300 W | Scenario assumption | A simple accelerator work unit, not provider telemetry. |
| Solver host power | 65 W | Scenario assumption | Approximate local CPU power for the projection. |
| PUE | 1.2 | Scenario assumption | Multiplies device energy by data-center overhead. |
| Prices | $0.003 input and $0.015 output per 1,000 tokens | Scenario assumption | Pricing knobs. Provider billing was not measured. |
| Electricity and carbon | $0.12 per kWh and 400 g CO2e per kWh | Scenario assumption | Illustrative conversion inputs. |

The benchmark environment was Python 3.14.7 on a 12th Gen Intel Core i5-12400F with 6 physical and 12 logical processors. The run used one Uvicorn process, no reload, no provider credentials, and no concurrent test suite. Background desktop activity remained, so the timings are local observations rather than controlled hardware benchmarks. The raw report stores the fixture SHA-256 and source commit for provenance.

### Reproduce the measured run

Start the application, then run:

```text
python -m benchmarks.run_benchmark --base-url http://127.0.0.1:8000 --repeats 5 --output docs/evidence/solver-five-runs.json
```

Run a live comparison only when you have configured providers and accept the paid-call cost:

```text
python -m benchmarks.route_benchmark --base-url http://127.0.0.1:8000 --live-routes --allow-paid-jev --routes solver,deterministic,jev,ai_only --repeats 5 --latency-budget-ms 5000 --output routed-results-live.json
```

The live comparison is still pending. Until it exists, the README must not describe the exact-route report as an AI speedup or claim measured provider energy, cost, or token savings.

Read [the evaluation guide](docs/evaluation.md) and [the measurement plan](docs/evidence/measurement-plan.md) for scoring, timing boundaries, and limitations.

## How this can expand

- Add more route labels for retrieval, code execution, vision, or specialist math tools.
- Add confidence thresholds and a safe fallback policy for low-confidence Jev decisions.
- Cache route decisions for repeated request shapes while keeping user data out of shared keys.
- Train or deploy a local decision classifier for private, low-latency routing.
- Add a larger workload mix with natural-language prompts, exact math, and unsupported requests.
- Add a manual rubric for explanation quality alongside the existing machine-readable answer score.
- Add dashboards for route choice, avoided general-model calls, latency, and provider cost.
- Add model and prompt version fields so benchmark results remain reproducible.

## Limits and claims

The exact route is authoritative only within its documented math boundary. Numerical samples are evidence, not a universal proof. AI answers and explanations are unverified. Jev selects a route and does not establish mathematical truth.

The project measures recorded model calls and selected local timing data. Provider token usage is unknown in the exact-route report. The project does not measure total cloud compute, energy, or GPU work. Do not describe the scenario projection as a completed provider performance result.

The visual editor is a presentation layer. It converts MathQuill input into the same bounded structured grammar used by the solver and never sends raw LaTeX to the API. MathQuill is included under the Mozilla Public License. See `web/assets/LICENSES.txt` for third-party notices.
