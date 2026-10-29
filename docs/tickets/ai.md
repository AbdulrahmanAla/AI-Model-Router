# Implement optional AI explanations and fallback

Implement `/api/ai` and provider configuration per [the spec](../spec.md), consulting [provider notes](../research/provider.md). Own `app/ai.py`, `tests/test_ai_api.py`, and the minimal app route integration needed. Depends on the bounded solver API.

Acceptance: exact solve is independent of credentials, explanation is grounded in recomputed solver result, explicit fallback and matched baseline output are unverified, usage is recorded without inventing missing counts, missing-key and provider failures are honest/redacted, bounded timeout and concurrency, no retries, fake external HTTP contract tests and no paid calls in tests.
