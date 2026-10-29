# Local delivery validation

## Scope and evidence

The implementation is a working local website, not the earlier static visual prototype. It covers structured single-variable derivatives, integrals, limits, and bounded polynomial equations. The default solve route never requests an explanation or model fallback automatically.

The user approved the layout and public API and browser test boundaries before implementation. Local checks precede direct merges. No PRs or GitHub Actions are used.

## Browser journey

The actual website at `http://127.0.0.1:8000` was exercised through the in-app browser on 29 October 2026:

- Enter submitted `x^3*sin(x)` and displayed the product-rule derivative with a numerical-evidence label.
- A definite integral of `x^2` from 0 to 1 returned `1/3` with a quadrature check.
- The two-sided limit of `sin(x)/x` at zero returned `1`.
- The equation `x^2-4=0` returned `{-2, 2}` with root-substitution details.
- An unsupported function produced a useful validation message while the solver stayed ready.
- Syntax help opened, displayed the allowlist, and closed with Escape.
- Session question search filtered the sidebar, and New chat cleared the session.
- Desktop sidebar collapse and reopen worked.
- Repeated submissions exposed an unbounded conversation layout. The final shell uses a viewport height and an internal scroll area. After the fix, the newest result remained visible above the composer on wide and narrow viewports.
- A narrow viewport displayed a real derivative result without horizontal page overflow in the captured view.
- Browser console inspection during these journeys returned no errors or warnings.

The wide and narrow viewport controls were set to 1366 by 900 and 390 by 844 respectively. Browser zoom and screenshot pixel scaling can make captured pixel dimensions differ from those requested values.

![Desktop result and route metrics](evidence/desktop-result.jpg)

![Mobile result after several questions](evidence/mobile-result.jpg)

## Evaluation protocol

The frozen fixture file has SHA-256 `EE15FF9C9E6733C99FB09B8BD96CF9E5746516059582AECD34EF4BC06D321DF2`. It contains 30 supported solved cases and ten boundary cases, for a total of 40. Expected answers are worked literals. A check using SymPy does not constitute an independent implementation of the same mathematics.

The first public HTTP run exposed three protocol mismatches. The scorer did not equate an empty real root set with the no-real-solutions sentinel, a resource-limit rejection did not match the bounded-input policy, and a disagreement between one-sided limits returned a solved result with a failed-check label. The scorer and result contract were corrected, with regression tests. The mathematical fixture answers were not changed after that run. The bounded-input scoring rule accepts a safe 422 response or an unresolved response. Neither counts as a solved answer.

## Optional AI browser contract

An isolated app on local port 8001 used a synthetic HTTP provider on port 9001 with model name `local-contract-fixture`. The response itself said it was a local fixture rather than a model answer. The main app on port 8000 was not connected to that fixture.

The browser solved `x^2` as `2*x`, then Explain preserved that exact answer and displayed `AI text · unverified`. The route showed one attempt and 43 synthetic tokens. An explicit Explain again action accumulated two attempts and 86 synthetic tokens. After the fixture provider stopped, another explicit attempt produced a redacted connection error, preserved `2*x`, counted three attempts, and marked total token usage unreported. Both temporary services were stopped after the check.

![Synthetic provider contract check](evidence/synthetic-ai-contract.jpg)

![Synthetic provider failure preserves the exact answer](evidence/synthetic-ai-failure.jpg)

These screenshots verify UI integration and accounting only. Their response text, timing, and token counts are synthetic test values and are excluded from efficiency evidence.

Final solver measurements are recorded after the final integration gate.

## Limits

Provider contract tests use a fake external HTTP transport and make no paid model calls. They validate requests, grounding, usage accounting, and failure handling. They do not establish live model quality, provider compatibility, token savings, or model inference latency.

No API key or external hosting configuration was supplied. Live provider comparison and external publication remain pending user-owned configuration. The local solver remains usable without them. The repository provides local environment instructions, a Dockerfile, and a manual HTTPS deployment guide. Docker is unavailable on this PC, so a container build has not been verified here.

No energy, FLOP, GPU-power, or total cloud-compute measurement is claimed.

## Final merged browser regression checks

The app was restarted from integration commit `5ec24e4` in the clean verification environment, without reload and without provider configuration. The final browser checks confirmed:

- `(0.100000000000000001-0.1)*x` differentiates to exact `1/1000000000000000000`.
- `x^2 = 1` returns `{-1, 1}` with substitution checks.
- `sin(x)=0` is unresolved on the polynomial route and offers explicit AI fallback. Without configuration, that action reports provider unavailable rather than an inconsistent grammar rejection.
- Explain without configuration preserves the exact result and reports provider unavailable.
- The indefinite integral of `1/x` displays `log(Abs(x))`, the omitted constant note, a nonzero-domain note, and numerical evidence rather than an unsupported symbolic proof.
- Route details show zero general-model calls for the exact integral. Browser console inspection returned no warnings or errors.

![Final real antiderivative and route details](evidence/final-integral.png)

The clean-environment final gate passed 61 pytest tests, JavaScript syntax, and real HTTP smoke of all 40 frozen cases. One upstream Starlette/httpx deprecation warning remains.


## Five-run solver-only evidence

Source commit `5ec24e43221fe6148498467725e969ea9a665d75`; Python 3.14.7; i5-12400F, 6 physical cores and 12 logical processors. One production-style Uvicorn process used the locked verification environment, no reload, no provider credentials, and serial requests. Other test suites were stopped. Background desktop activity remained, so latency is a local observation rather than a controlled hardware comparison.

Across five repetitions of the unchanged 40-case set, all 150 supported solved observations were correct. All 50 boundary observations matched their expected safe behavior. There were zero failed outcomes and zero transport failures. Each repeat contained 30 solved cases, five grammar rejections, four unresolved cases, and one bounded-input refusal. These boundary cases are excluded from supported-answer accuracy.

All 200 requests recorded zero general-model calls with no unknown call counts. Provider token usage remains unreported, rather than being invented as zero. This establishes call avoidance on this fixed set only. It does not establish equal quality to a live AI baseline, token savings against a model, or a hardware-compute reduction.

Median HTTP latency over all outcomes was 585.12 ms, with observation range 515.20 to 1278.83 ms. The five per-repeat HTTP medians were 590.93, 601.46, 580.17, 569.96, 561.45 ms; their median was 580.17 ms and range 561.45 to 601.46 ms. Fast rejections contribute to this all-outcome distribution. Fresh subprocess startup and math imports are material overhead, as the separate import diagnostic shows. No AI latency comparison was run.

[Raw requests, responses, scores, counters, and environment](evidence/solver-five-runs.json). [Measurement protocol](evidence/measurement-plan.md).

## Repository completion and cleanup

The reviewed integration was directly merged into `main`, pushed, and made the GitHub default branch. All in-scope GitHub issues, including the Wayfinder map, are closed with evidence links. No PR or GitHub Actions run was created.

Managed-worktree cleanup was attempted through the Codex archive tool. The app refused to archive the solver, website, and evaluation worktrees because active tasks still reference them, and refused the review worktree as a primary checkout. These recoverable local checkouts were retained. No checkout was deleted manually. The final local server remains on port 8000; synthetic-provider services are stopped.

## Deterministic solution steps

Commit `ddfb026` adds a bounded `steps` list to every solver response that reaches the public solve contract. Solved requests describe the actual route for derivatives, indefinite and definite integrals, limits, and polynomial equations. Unresolved requests include a stopping step that names why the exact route stopped. Each list is limited to eight entries of 500 characters or fewer.

The website renders the list as an expandable **Show steps** section inside the answer card. Route metrics remain separate. AI explanations remain optional and are never used to generate these steps. The browser check submitted `x^3*sin(x)`, expanded **Show steps**, and displayed the product-rule route plus the numerical verification step. The API returned the same steps at `/api/solve`.

![Expanded deterministic solution steps](evidence/solution-steps.png)

## Visual math editor validation

The composer now uses a bundled MathQuill 0.10.1-a field for the expression, integral bounds, and limit target. The MathQuill stylesheet, jQuery dependency, JavaScript build, and Symbola fonts are served locally from `web/assets`, so the editor does not depend on a CDN during the demo.

The live page was reloaded from the updated server and showed the MathQuill editable-field class on the expression control, the MathQuill stylesheet loaded, and the expected visual equation input area. The editor remains a presentation layer: the browser converts supported MathQuill LaTeX to the existing structured expression grammar before submitting `/api/solve`. The solver API and 40-case evaluation contract are unchanged.

![MathQuill visual equation editor](evidence/mathquill-editor.png)

MathQuill supports visual fractions, roots, exponents, function names, and symbols. Integral and derivative workflows continue to use the existing operation selector and bound fields. The editor does not claim support for new mathematical operations, implicit variables, or arbitrary LaTeX.
