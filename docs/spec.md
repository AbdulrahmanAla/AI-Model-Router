# AI Math Assistant implementation spec

## Destination

Build a working, locally tested website for students learning calculus and algebra. Show that supported structured calculations can avoid general-model calls. Compare correctness, calls, reported tokens, and latency with an AI-only baseline when a provider is configured. Do not claim measured energy, FLOPs, or model speedups without those measurements.

The user approved the current ChatGPT-style layout and the test boundaries on 29 October 2026. The user requested completing the tickets, overriding the earlier one-decision-per-session planning limit. Source and tickets live on GitHub. Local checks precede direct merges. No PRs or GitHub Actions.

## Scope

- Derivatives, indefinite and definite integrals, limits, and real polynomial equations of degree at most four.
- One real variable named `x`. The composer uses a visual equation editor with a bounded adapter for supported MathQuill constructs and offers plain typed formulas if the editor library is unavailable. Arbitrary pasted LaTeX, natural-language interpretation, matrices, plots, accounts, and durable storage are outside this implementation.
- Chat-style dark website with a narrow sidebar, centered conversation, bottom composer, teal accent, and product name AI Math Assistant.
- Exact answer, honest check status, collapsible route metrics, and optional Explain button. No automatic AI call on submit or error. An explicit Ask AI fallback action is available for a valid request the solver cannot finish.
- Display familiar exact-result notation with the bundled MathQuill static renderer, including fractions, ordinary roots, powers, and finite sets. Keep the authoritative typed answer for accessibility, copying, and session evidence. Unknown commands, indexed roots, excessive notation, or renderer failure retain the typed answer instead of risking a partial visual formula. No new network dependency or AI call is needed for formatting.
- Session-only conversation history, new chat, supported syntax help, mobile layout, keyboard submission, loading state, readable errors, and accessible labels.
- Submitting a question and receiving its result reveal the start of that question inside the conversation pane. Reveal a completed result only when the student is still following the conversation near its bottom; preserve their position if they scrolled up. Scrolling a new answer must not move the outer page or hide the header.
- A worked-example gallery is available from the welcome screen and sidebar. Its eight presets demonstrate chain rule, substitution, integration by parts, definite bounds, a one-sided limit, a two-sided limit that does not exist, quadratic roots, and a real-domain refusal. Selection restores the complete operation context and focuses the composer without submitting or calling AI. The native dialog supports Escape, keeps its close control visible while scrolling, and participates in the modal shortcut guards.
- The route explanation and session export summarize current question outcomes, solved-result check types, explicit AI attempts, model calls, and provider-reported tokens. Question counts reflect the current outcome after a retry; AI usage includes recorded attempts. Missing usage on any AI attempt makes that usage total unknown. Solver-only questions and solver failures do not invalidate known provider usage. The summary identifies session activity separately from held-out evaluation, live model comparison, energy, and FLOPs.

## Runtime and grammar

Use FastAPI to serve static HTML, CSS, and JavaScript and a same-origin JSON API. No frontend build tool is required. Keep API keys on the server. SymPy runs in a bounded subprocess, with a wall-clock timeout, limited concurrent work, and strict input limits. Never use eval, exec, sympify on input strings, parse_expr, or arbitrary LaTeX parsers.

Parse an allowlisted arithmetic AST. Accept integers and exact decimals, `x`, `pi`, `E`, parentheses, unary signs, `+ - * / ^ **`, and one-argument `sin cos tan exp log sqrt Abs asin acos atan sinh cosh tanh`. The server grammar requires explicit multiplication. The visual adapter inserts multiplication only between adjacent supported factor tokens, then submits the same typed grammar. Reject attributes, strings, containers, subscripts, unknown names, keyword arguments, extra variables, excessive size/depth, and excessive numeric constants/exponents before expensive work. Limits and bounds accept constant expressions, with `oo` and `-oo` where appropriate. Equations accept one `=` or an expression equal to zero and share the same function grammar. The exact equation route solves real polynomials of degree at most four; other valid equations return unresolved so the explicit AI fallback can handle them. Variable denominators that simplification could hide remain rejected.

## API contract

`GET /api/health` returns `{status: "ok", ai_configured: boolean}` without secrets.

`POST /api/solve` accepts:

```json
{"operation":"derivative", "expression":"x^3*sin(x)", "variable":"x", "lower":null, "upper":null, "target":null, "direction":null}
```

Operations are `derivative`, `integral`, `limit`, and `equation`. Integral bounds must appear together. Limits require target and direction `both`, `+`, or `-`. All unnecessary fields must be absent or null, including direction outside a limit request. Invalid JSON or unsafe grammar returns a helpful 422 response. A request which parses but cannot be answered safely returns a normal `unresolved` result. Busy server returns 503. Solver deadline returns `unresolved` with timeout status. No automatic retries or AI fallback.

Every successful API response to solve contains:

```json
{
  "status":"solved",
  "operation":"derivative",
  "expression":"x^3*sin(x)",
  "result":"3*x**2*sin(x) + x**3*cos(x)",
  "latex":"...",
  "verification":{"status":"numerical_evidence", "method":"...", "detail":"..."},
  "notes":[],
  "metrics":{"route":"solver", "ai_calls":0, "solver_ms":0.0, "elapsed_ms":0.0, "model":null, "input_tokens":null, "output_tokens":null, "total_tokens":null}
}
```

Unresolved responses have a null result and latex, a helpful note, and `verification.status = "not_checked"`. Verification statuses are `symbolic_check`, `numerical_evidence`, `not_checked`, and `failed`. These describe checks, not a universal proof. Every result includes the original structured request as `request` so explanation and fallback can be reproduced without server conversation storage.

`POST /api/ai` accepts `{ "action":"explain" | "fallback" | "baseline", "request": <SolveRequest> }`. Validate and bound this input using the same request schema and grammar as solve. For Explain, recompute the solver result, decline if unresolved, then ground the prompt in that answer and its check status. Ignore any client-supplied answer or metrics. Fallback and baseline return unverified model text. Their matched answer contract uses real variable `x`, typed formulas, no arbitrary integration constant `C`, and the equation sentinels `all real x` and `no real solutions`. Return `{status:"answered", text:"...", verification:{status:"not_checked",method:"AI output",detail:"..."}, metrics:<same metric fields>}`. Missing config is 503, timeout is 504, provider failure is 502. Error bodies include call/usage metrics when a call was attempted; never pretend a failed request used zero calls. Report missing provider token usage as null, never as zero. Never forward raw provider errors, credentials, or provider URLs to the browser. Server configuration uses `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`, and optional timeout/token limits. No hardcoded paid model or fabricated explanation.

## Math checks and boundaries

- Worked integral steps include a complete integration-by-parts calculation for a linear polynomial factor times `sin`, `cos`, or `exp` with a nonzero linear inner slope. Show the choices of `u` and `dv`, the scaled primitive `v`, and the remaining integral. This is a bounded educational derivation, not a trace of SymPy internals or a claim to cover every integral.
- For a polynomial inner function `g(x)` of degree at least two inside `sin`, `cos`, or `exp`, show substitution when the other factors form a polynomial that is exactly a constant multiple of `g'(x)`. Show the inner function, its differential, the scaling, integration in `u`, and substitution back. Check the whole differential identity rather than matching only leading coefficients. Other patterns retain the existing derivation route.
- Derivatives: independently compare numerical derivative estimates against the symbolic result at suitable real finite points. Label numerical evidence, never a proof or differentiation-back check. Domain failures do not become passed checks.
- Antiderivatives: differentiate the returned expression and simplify the residual against the input. Explain domain restrictions and the arbitrary constant. Use `log(Abs(...))` for real logarithmic branches and state the excluded zeros, or return unresolved rather than a misleading complex branch.
- Definite integrals: reject interior singularities and uncertain real-domain intervals. Do not present a Cauchy principal value as an ordinary integral. Independently compare numerical quadrature where safe. Mark absence of independent evidence honestly.
- Limits: compare left and right for a two-sided finite-point limit. A disagreement means the two-sided limit does not exist. Numerical samples are evidence only. Infinity and oscillation are not finite numerical success.
- Equations: real polynomial roots only. Substitute every root. State whether the returned set is the solver's complete real solution set and distinguish that from substitution checks. Identity and inconsistent equations have explicit results.
- Rational-coefficient polynomials use exact real-root isolation, with repeated roots returned once. Other coefficient domains require exact symbolic realness classification; indeterminate classification stops the route rather than using a floating-point imaginary-part tolerance. Irreducible cubics and quartics may display `CRootOf(p(x), k)` as an exact indexed algebraic root, with an explanatory note. This output notation does not extend the accepted input grammar.

## Local verification boundaries

User confirmed tests at three public boundaries: math API, AI API boundary, and browser journey. API tests cover known worked answers, rejection, domain failures, timeouts, no-key operation, explicit AI calls, usage accounting, malformed/provider errors, and secret redaction. Use fake HTTP transport only at the external provider boundary. Label those tests as contract checks, not a successful live model evaluation. UI verification exercises actual submit, result, details, help, reset, error, optional AI failure, desktop, and mobile. A screenshot alone does not pass the journey.

## Evidence

Create 40 frozen evaluation cases, ten per operation. Expected answers are independently worked literals, not generated by the solver under test. Include regular problems, domain issues, divergent limits, unsupported valid inputs, and grammar rejections. Store IDs, expected outcome and value, source/rationale, and scoring rules. Keep evaluation fixtures out of product code.

The CLI benchmark calls the running HTTP API, validates outputs, records every case, elapsed wall-clock latency, solver time, model calls, per-model reported usage, failures, and correctness. It supports solver-only validation without a key and an explicit opt-in live comparison against the same configured model with matched task/output expectations. Count explanation and fallback calls in their own scenario. Alternate route order across repeated paired trials. Summarize medians and ranges and flag unknown tokens. Never label a solver-only run an AI comparison. No energy or total compute claim. Targets are a correctness tie on supported scored cases and reduced general-model calls for the default workflow, with no unsupported universal guarantee.

## Delivery

Pinned Python dependencies, `.env.example`, local run/check commands, Dockerfile and manual deployment instructions with HTTPS/secret configuration. A local production-style smoke test must pass. External hosting and live provider benchmarking require user-owned service credentials and remain explicitly pending if unavailable. Do not create a fake deployment URL or close a task claiming a live comparison occurred.

Implementation units: bounded solver API, functional chat website, optional AI API contract, evaluation harness, and local/manual delivery. Each unit is implemented on a branch from `codex/ai-math-assistant`, checked locally, and merged directly. Final review compares against prototype commit `d75f7f9` and this spec.
