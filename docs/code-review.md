# Integration code review

The review compared prototype commit `d75f7f9` with integration candidate `a2719d3`. Two independent agents reviewed the standards and spec axes. The spec source was `docs/spec.md`. There was no repository coding-standards file beyond the user's instruction to avoid em dashes.

## Standards

No hard documented-standard breaches were found. The reviewer identified these maintainability judgments:

- Validation metrics were repeated in several handlers in `app/main.py`. A shared helper would keep those responses consistent.
- AI validation duplicated equation, bound, and limit parsing and used private solver helpers. A shared public validation function would reduce coupling and grammar drift.
- Internal request and metrics dictionaries could use stronger types if the application grows.
- Provider configuration, prompts, transport, and response validation could split into separate modules if the AI adapter grows.

The first two suggestions were accepted for the correction pass. Broader type and module changes are deferred because the external boundary already uses Pydantic, the prototype has one configured provider, and the reviewer classified them as nonblocking design judgments.

## Spec

The reviewer found four material issues:

1. A definite integral of `sqrt((x-1)*(x-2))^2` over `[0,5]` returned a result with numerical evidence even though the original square root is non-real on `(1,2)`. Endpoint and midpoint sampling cannot establish an entire interval's real domain.
2. Decimal literals passed through Python binary floats before conversion to exact rationals. The derivative of `(0.100000000000000001-0.1)*x` incorrectly returned zero. Scientific underflow such as `1e-999*x` also became zero.
3. Separately parsed equation sides retained whitespace. `x^2 = 1` was rejected because its right side began with a space.
4. A non-polynomial equation such as `sin(x)=0` produced an unresolved solver result but an AI grammar rejection, making the offered fallback unusable.

All four findings were accepted. A single implementation worker owns their correction and regression tests. The grammar clarification permits safe structured non-polynomial equations to reach an explicitly requested unverified AI fallback, while the exact equation path remains limited to polynomials of degree at most four.

Initial review totals: no hard standards breaches, four nonblocking standards suggestions, and four material spec findings. The worst spec findings concern incorrect exact results and unsupported domain-verification claims. Correction evidence is recorded after the final gate.
