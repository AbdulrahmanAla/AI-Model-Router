# AI Math Assistant with Jev routing

AI Math Assistant is a chat-style math website for derivatives, integrals, limits, and simple real polynomial equations. It parses a bounded structured request, solves supported math with SymPy, and shows the result with steps and a check status.

The exact solver is the default path. It does not need a general-purpose language model. Optional AI actions can explain an exact result, answer a request that needs language generation, or provide a fallback for work outside the exact solver's boundary.

The project also includes an optional Jev route. Jev makes a small route decision before the application chooses the exact solver, an AI model, or a refusal. The decision is recorded next to the answer so you can see why a route was selected and how many model calls it used.

## What the project does

- Solves supported derivatives, integrals, limits, and real polynomial equations with SymPy.
- Checks results with symbolic checks, substitutions, numerical samples, or numerical quadrature when the operation allows it.
- Returns `unresolved` when a request is valid but outside the safe supported boundary or the solver deadline.
- Validates the input grammar and rejects unsafe or malformed requests before expensive work.
- Provides optional AI explanations that are grounded in an exact result. AI prose remains unverified.
- Accepts an optional plain-language prompt through the AI route. A prompt is never passed to SymPy as executable math.
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
+-- Exact mode: POST /api/solve
|   |
|   +-- Validate the request schema and bounded expression grammar
|   +-- Run the SymPy solver in a bounded worker
|   +-- Check the result and return steps, notes, and metrics
|
+-- Routed mode: POST /api/route
    |
    +-- Accept exactly one structured request or one plain-language prompt
    +-- Validate structured math before any route model call
    +-- deterministic
    |   +-- Structured request -> exact SymPy solver
    |   +-- Plain-language prompt -> configured AI provider
    +-- jev
    |   +-- Jev decision classifier -> solver, ai, or refuse
    |   +-- Jev unavailable -> deterministic fallback
    |   +-- solver -> exact SymPy result
    |   +-- ai -> configured AI provider
    |   +-- refuse -> explicit refusal with routing evidence
    +-- ai_only
        +-- Send the matched task to the configured AI provider
```

The main code is organized around these units:

```text
AI-Math-Assistant/
|-- app/
|   |-- main.py       # FastAPI endpoints and request validation
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

Open [AI Math Assistant locally](http://127.0.0.1:8000). Choose an operation and enter a formula such as `x^3*sin(x)`. The visual editor supports fractions, exponents, roots, trigonometric functions, and symbols. Typed input uses explicit multiplication such as `2*x`.

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

## Benchmark status

The benchmark harness is ready, but the final Jev versus exact versus AI comparison is still in progress. The table below is a placeholder. Replace each `pending` value with a measured result from the same frozen cases and repeated route order.

| Route | Cases | Accuracy | Median latency | General-model calls | Token usage |
| --- | ---: | ---: | ---: | ---: | ---: |
| Exact solver | 40 | pending | pending | pending | pending |
| Deterministic route | 40 | pending | pending | pending | pending |
| Jev route | 40 | pending | pending | pending | pending |
| AI-only route | 40 | pending | pending | pending | pending |

Run the solver-only benchmark without provider calls:

```text
python -m benchmarks.run_benchmark --base-url http://127.0.0.1:8000 --repeats 5 --output benchmark-results.json
```

Run the routed comparison only when the providers are configured and you accept the paid-call cost:

```text
python -m benchmarks.route_benchmark --base-url http://127.0.0.1:8000 --live-routes --allow-paid-jev --routes solver,deterministic,jev,ai_only --repeats 5 --latency-budget-ms 5000 --output routed-results-live.json
```

The routed benchmark reports answer accuracy, successful tasks, route overhead, model calls, prompt and completion tokens, wall latency, explicit local CPU and memory observations when available, and failed outcomes. It keeps missing provider usage as unknown. It does not infer energy, FLOPs, hosted GPU work, or a universal speedup.

Read [the evaluation guide](docs/evaluation.md) for the scoring rules and the live comparison boundary.

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

The project measures model calls, provider-reported tokens, and selected local timing data. It does not measure total cloud compute, energy, or GPU work. Do not describe the pending table as a completed performance result.

The visual editor is a presentation layer. It converts MathQuill input into the same bounded structured grammar used by the solver and never sends raw LaTeX to the API. MathQuill is included under the Mozilla Public License. See `web/assets/LICENSES.txt` for third-party notices.
