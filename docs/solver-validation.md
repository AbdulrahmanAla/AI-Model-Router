# Solver validation

The public API tests run through FastAPI `TestClient` and cover the agreed math API seam. They use fixed worked answers and do not call a model provider.

Command:

```powershell
C:\Users\D7my\Documents\ChatGPT\HUMAIN\.venv\Scripts\python.exe -m pytest -q tests/test_math_api.py
```

Latest local result: 69 passed across the full project gate. The suite covers derivatives, derivative domain caveats, indefinite and definite integrals including infinite bounds, finite and infinite limits, equations, non-existent limits, real-domain approach failures, unsafe syntax, implicit multiplication, exponent towers, variable denominators, malformed operation fields, solver saturation, deadline handling, static home serving, and secret-free health output.

The solver uses a spawned worker with a two-process semaphore and `SOLVER_TIMEOUT_SECONDS` (default 8). A `SOLVER_TIMEOUT_MS` environment override remains available for focused tests. The worker returns its own SymPy compute time, while the API reports full request elapsed time separately.

The exact route reports zero model calls. Verification labels distinguish numerical evidence, symbolic checks, failed checks, and unchecked results. Numerical samples do not claim a proof.

The test run emits one upstream Starlette deprecation warning about its `httpx` test client import. It does not affect the result.
