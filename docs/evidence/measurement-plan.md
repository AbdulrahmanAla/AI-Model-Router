# Solver-only measurement plan

## Claim under test

On the frozen 40-case local set, five serial HTTP repetitions return the expected supported answers and boundary behavior with zero general-model calls. The report records local end-to-end latency and worker solve time. It does not compare AI quality or AI speed and does not measure energy, FLOPs, or total compute.

## Procedure

1. Complete the review corrections and local merge gate before recording measurements.
2. Start one production-style Uvicorn process without reload and without provider credentials.
3. Keep the 40-case fixture file unchanged. Record its SHA-256 and the source commit.
4. Record the CPU model, logical processor count, Python version, and current total CPU activity. Avoid running other local test suites concurrently with the measurement.
5. Run the public HTTP CLI with `--repeats 5` and no `--live-ai` option.
6. Inspect every case outcome, correctness score, transport failure, and route counter. Do not treat a fast rejection as a correct solved answer.
7. Report supported-answer accuracy separately from boundary handling. Report the distribution of client wall-clock latency and the median and range of per-repeat medians.
8. Keep the raw report and link it from the delivery validation record. Keep missing model token usage null. It is not a paid-provider measurement.

The CLI serializes each JSON request before starting its timer, then times HTTP transmission and response-body retrieval. The response carries worker computation time separately. Each solve uses a fresh spawned worker, so the HTTP timing includes process startup and math-runtime imports. JSON decoding and scoring run after the timed request and are not part of client latency.

An optional diagnostic import profile is separate from the reported trials. It can help identify startup overhead, but it cannot establish an AI speedup or hardware compute ratio.

## Startup diagnostic

On candidate `ae3137d`, a separate fresh-process run of `python -X importtime -c "import app.solver"` recorded cumulative imports of 367132 microseconds for SymPy and 457521 microseconds for `app.solver`. The process elapsed time was 537.035 milliseconds. These are one diagnostic observation with instrumentation, excluded from the reported trials. They establish that startup is material to this spawned-worker design, not an exact latency decomposition for every request.
