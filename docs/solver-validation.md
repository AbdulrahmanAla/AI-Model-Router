# Solver validation

The public API tests run through FastAPI `TestClient` and cover the agreed math API seam. They use fixed worked answers and do not call a model provider.

Command:

```powershell
C:\Users\D7my\Documents\ChatGPT\HUMAIN\.venv\Scripts\python.exe -m pytest -q tests/test_math_api.py
```

The suite covers derivatives with concrete transformation steps and domain caveats, indefinite and definite integrals including infinite bounds, finite and infinite limits with one-sided evidence, equations including identity and constant boundaries, non-existent limits, real-domain approach failures, unsafe syntax, implicit multiplication, exponent towers, variable denominators, malformed operation fields, solver saturation, deadline handling, static home serving, secret-free health output, and oversized AI response rejection at the provider boundary. Empty real root sets retain a solver result but receive `not_checked` verification: substituting an empty list cannot independently establish that no real roots exist. Public API tests cover both quadratic and quartic examples.

The solver uses a spawned worker with a two-process semaphore and `SOLVER_TIMEOUT_SECONDS` (default 8). A `SOLVER_TIMEOUT_MS` environment override remains available for focused tests. The worker returns its own SymPy compute time, while the API reports full request elapsed time separately.

The exact route reports zero model calls. Verification labels distinguish numerical evidence, symbolic checks, failed checks, and unchecked results. Numerical samples do not claim a proof.

The test run emits one upstream Starlette deprecation warning about its `httpx` test client import. It does not affect the result.

Real-logarithm linearity steps use the same Abs transformation as the final antiderivative. Public API tests cover sums with singularities at zero and at one. Branch notes explicitly preserve the original integrand's real domain.

Sine, cosine, and exponential integrals with a linear argument show the concrete substitution, differential scaling, and substituted-back antiderivative. Worked public API cases include a shifted sine, scaled cosine, and negative exponential slope. The shortcut requires a nonzero constant inner derivative.

Power integrals show n and n + 1, division by the new exponent, and the separate n = -1 logarithm rule. Constant integrands show multiplication by x; scalar multiples name the extracted factor and retain the remaining power or substitution steps. Worked API cases cover positive and negative powers, the logarithm exception, constants, and a scaled sine.

Finite polynomial definite integrals show the termwise antiderivative, both endpoint values, and F(b) - F(a). Worked API cases cover a monomial, a linear polynomial with a negative lower endpoint, and a constant integrand. Infinite bounds and nonpolynomial integrands retain their existing route descriptions.
