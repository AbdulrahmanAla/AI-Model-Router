# Local AI and Jev routing implementation

This extends the existing math spec. Source decisions are the free AI boundary, router contract, and compute metric tickets in the GitHub map.

## Routes

The existing `/api/solve` remains an exact zero-model endpoint. `/api/ai` remains explicit explanation, fallback, or baseline. Add `/api/route` for an explicitly selected routed workflow. It accepts exactly one of a bounded structured `request` or a bounded plain-language `prompt`, plus mode `deterministic`, `jev`, or `ai_only`. A prompt is data for a language model, never executable solver input. Structured requests pass existing schema and bounded grammar checks before any routing call. A language prompt cannot reach SymPy without a validated structured translation; this first version instead uses local AI for language prompts and honestly identifies that boundary.

In `jev` mode, a configured server-side Jev adapter chooses `solver`, `ai`, or `refuse`. A `solver` choice on a language-only request cannot run SymPy and falls back safely to AI with a route note. Jev failure or missing configuration falls back to the deterministic classification and records attempted routing calls, errors, and unknown usage. A refusal stays explicit. Deterministic mode uses SymPy for validated structured requests and local AI for language requests. AI-only mode sends the matched task to the configured model, without solver assistance, for evaluation. Do not silently promote unresolved math to AI without the explicit routed/AI action.

Exact results remain authoritative when returned. AI answers and explanations stay unverified. Jev chooses routing, not mathematical truth. Router decisions never cause arbitrary code execution or modify a returned exact answer. Keep request-size limits, bounded concurrency, output limits, and sanitized errors. Configuration and credentials are server-only. Disabled or unavailable AI does not break the existing solver.

## Local provider

`AI_PROVIDER=ollama` selects local native `/api/chat` with nonstreaming responses. Require a configured local model and default to loopback. Do not send hosted credentials to Ollama. Record native prompt/evaluation counts and durations when reported, without inventing missing values. Keep hosted OpenAI-compatible configuration available separately. Document local setup and a small reproducible model choice. Installation, real inference, and GPU use require observed evidence.

## Evidence and UI

Return router source, choice, fallback reason, per-attempt provider/model calls, token counts, and timing separately from the final answer. Include failed routing attempts. Never total incomplete usage as known. UI exposes optional Jev routing and natural-language AI entry without changing default exact math. Copy/export preserve routing metadata. Unknown Jev credentials or missing Ollama show clear recovery states.

Compare the same frozen cases with the same answer scoring across exact/deterministic, AI-only, and Jev routes. Include the routing overhead and failures, repeat and alternate order, record cold/warm state and model identifiers. Report calls and tokens per successful task; tokens across different models are separate usage proxies, not equal FLOPs. Report wall latency, attributable local CPU time, sampled peak memory, and measurement scope. Hosted CPU/GPU is unavailable and remains unknown. GPU work is not captured by CPU time. A latency budget is a declared evaluation parameter, not a claimed achieved floor. A correct answer outside that budget is a deadline failure. Explain prose requires a separate rubric and cannot pass on response shape alone. Live paid calls need explicit opt-in and user credentials. Contract fixtures never establish live quality or savings.

## Delivery gates

Public math/AI/routing API tests with fake external transports; frontend behavior tests; actual browser submit/result/explain/failure journey; real local model smoke; existing full gate; independent standards and spec reviews. Direct merge after verification. No PRs or GitHub Actions. Keep live Jev evaluation pending if credentials are absent rather than fabricating it.
