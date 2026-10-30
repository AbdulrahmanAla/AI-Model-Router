# Live Jev routing benchmark

Run on 30 October 2026 against the local server with one alternating-repeat pass over the 40 frozen cases. The Jev API key was loaded from the ignored local `.env` file. No key is stored in this repository.

The exact solver passed all 40 observations with a median wall latency of 591.9 ms and zero model calls. Jev routing made 40 routing attempts. Jev returned usable usage metadata for 34 calls: 15,619 input tokens, 1,327 output tokens, and 16,946 total tokens. The median Jev latency was 2,090.4 ms. Six Jev attempts had unknown usage and are excluded from known token totals. One case, `integral-09`, was refused by Jev where the frozen case expected an unresolved solver response, so Jev routing had 39 successful tasks and a 97.5% task success rate under the existing scorer.

This is evidence about one model version, one PC, one API key, one pass, and one frozen workload. It is not a universal quality or compute claim. CPU and memory measurements cover the local server process only. Hosted Jev compute and energy are unknown. The raw observations are in [jev-live-benchmark.json](jev-live-benchmark.json). Ollama was not installed, so no local-model comparison was included.
