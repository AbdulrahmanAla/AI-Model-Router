# Implement the bounded solver API

Implement the runtime, safe structured grammar, solver deadline, correctness checks, and JSON API in [the spec](../spec.md). Own `app/`, `tests/test_math_api.py`, `requirements.txt`, and `requirements-dev.txt`. The optional AI API is implemented by a separate ticket after this boundary exists.

Acceptance: local public-API tests for all four operations, invalid/unsafe inputs, real-domain failures, deadline and concurrency behavior. Exact route makes zero model calls. Check status is honest. No eval-based parser. Pin dependencies. Serve `web/` from the same origin when it exists. Use user-confirmed TDD at the API boundary.
