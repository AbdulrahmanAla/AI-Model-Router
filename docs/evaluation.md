# Evaluation harness

The harness measures the public HTTP route. It does not import application internals or derive expected answers by running the application solver. The fixtures in `benchmarks/cases.json` contain 40 independently worked cases, ten each for derivatives, integrals, limits, and equations.

Each case has one expected outcome:

- `solved` has a literal result and belongs in supported-answer accuracy.
- `unresolved` is a valid request that the bounded assistant may decline because of a domain, size, oscillation, identity, or unsupported-degree condition.
- `rejected` is outside the grammar and belongs in validation correctness, not solved-answer accuracy.

The scorer parses result text through a small allowlist of arithmetic operators, symbols, and functions. It accepts the `erf` special function in returned Gaussian primitives. For indefinite integrals it differentiates the difference, so arbitrary constants do not cause false failures. It never calls `eval`, `exec`, `sympify`, or an unrestricted expression parser. It uses symbolic equivalence only after the result has passed that allowlist. Equation roots are compared as sorted real values. The identity and inconsistent equation sentinels are `all real x` and `no real solutions`. An HTTP error, missing result, malformed model text, or provider transport failure is not a correct mathematical answer.

## AI baseline contract

When `--live-ai` is explicitly supplied, the runner calls `/api/ai` with `action: "baseline"`. The server prompt must require a single JSON object and no prose:

```json
{"status":"solved","result":"2*x"}
```

`status` is `solved`, `unresolved`, or `rejected`. A solved derivative, integral, or limit uses the same typed formula notation as the fixture, with no arbitrary integration constant `C`. A solved polynomial equation uses a JSON array of sorted real root strings; the identity and inconsistent sentinels are `all real x` and `no real solutions`. Unresolved and rejected answers use `"result": null`. The runner scores an AI answer only when it is valid JSON with the expected status and result, then applies the same allowlisted result comparison as the exact route. A non-empty explanation is never treated as a correct answer. Non-polynomial symbolic equation families are available through the explicit fallback action and remain unverified.

Requests rejected by shared validation are excluded from the AI solved-answer denominator. The baseline still records that the request was rejected when the server returns a validation response. Valid deferred or out-of-scope cases are recorded for manual review and are excluded from the solved-answer denominator. Transport errors, missing configuration, malformed JSON, and provider failures are recorded as failures and do not count as AI refusals.

`--ai-actions baseline,explain,fallback` can opt into the additional provider scenarios. `explain` is checked for a response and usage metrics, but its prose is not scored as a mathematical answer. `fallback` is scored with the same JSON contract and remains unverified. No provider call runs unless `--live-ai` is present.

## Commands

Start the app with its documented local command, then run:

```text
python -m benchmarks.run_benchmark --base-url http://127.0.0.1:8000 --output benchmark-results.json
```

Run five alternating solver trials and save raw responses:

```text
python -m benchmarks.run_benchmark --base-url http://127.0.0.1:8000 --repeats 5 --output benchmark-results.json
```

Run an explicit live comparison only when a provider key is configured:

```text
python -m benchmarks.run_benchmark --base-url http://127.0.0.1:8000 --live-ai --ai-actions baseline,explain,fallback --output benchmark-results-live.json
```

The report includes each raw response, HTTP status, case score, elapsed wall-clock time, server solver time, route model calls, and prompt, completion, and total tokens. Missing provider usage remains `null` and is counted as unknown. The summary reports median and range for observed timings, supported-answer accuracy, boundary counts, an explicit failed-outcome count across every case, and known call/token totals. A total is `null` when any value in that series is unknown; the known subtotal remains visible. It does not infer FLOPs, energy, or total compute.

The CLI defaults to a 60-second client timeout so it covers the configured provider and bounded validation deadlines. If those server limits are increased, pass a timeout longer than their total expected path.

## Initial run corrections

The first solver-only run against the 40 frozen cases found 29 of 30 supported solved answers and exposed three contract mismatches. The equation solver returned `{}` for the independently expected `no real solutions` sentinel, so the scorer now treats an empty finite set and that sentinel as equivalent. A valid oversized exponent was rejected with HTTP 422 before expensive work, so the `bounded_input` category accepts either that safe rejection or an `unresolved` response. A two-sided limit whose one-sided values disagree now returns `unresolved` with a null result and a note containing both one-sided values. These outcomes are recorded as boundary behavior and remain outside the solved-answer accuracy denominator where appropriate.

Solve validation and grammar rejections report `route: "validation"` and `ai_calls: 0` metrics. This keeps the no-provider exact route distinguishable from an unmeasured provider attempt while preserving unknown token fields.

## Reading a report

The solver claim is supported only when the supported solved cases are correct and the default exact route records zero model calls. Unresolved and rejected cases are reported separately. A live AI comparison is pending when no provider key is configured. A solver-only report is evidence about the exact route and its local latency, not an AI speed or token comparison.
