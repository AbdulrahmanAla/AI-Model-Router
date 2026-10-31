# Ollama live validation

Recorded with the local Ollama server and model `llama3.2:1b` on 31 October 2026.

- Ollama version: `0.40.13`
- Model size: `1.3 GB`
- Endpoint: `http://127.0.0.1:11434`
- Model Router route: `POST /api/route`
- Result: HTTP 200, `answered`
- Warm application latency: about 360 ms
- Reported usage: 65 input tokens, 49 output tokens, 114 total tokens
- Provider status: `ok`

Raw evidence is in [ollama-live-benchmark.json](ollama-live-benchmark.json).

This is a runtime smoke check, not a quality benchmark. The model output remains unverified. Exact supported math continues to use the local solver, and no energy or FLOPs claim is made.
