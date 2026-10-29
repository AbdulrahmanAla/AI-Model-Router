# Implement the evaluation cases and comparison harness

Implement `benchmarks/` per [the spec](../spec.md). Own fixtures, CLI runner, scoring code, and focused harness tests. Depend on solver and AI API tickets for final validation. Do not change application implementation.

Acceptance: 40 frozen independent worked cases across four operations, explicit outcome/answer/scoring rationale, public HTTP route timing and correctness, solver-only mode and opt-in live matched-output AI comparison, per-case raw JSON, unknown token accounting, route order alternation across repeat trials, no energy or inferred total-compute claim. Provider answers should have a constrained machine-readable answer shape and must not be auto-scored as correct just because text exists. Report rejected and unresolved separately from solved accuracy. Keep live comparisons pending without a key.
