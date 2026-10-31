# Implement the working chat website

Implement `web/` from [the spec](../spec.md), following the approved prototype in `.scratch/ai-hackathon-environment/prototype/math-assistant-ui.html`. Connect the same-origin API. Own only `web/` and optional browser test files outside `tests/test_math_api.py`.

Acceptance: user can choose any MVP operation, enter a formula and needed options, submit, read the result and real check status, inspect route metrics, and explicitly request explanation or fallback. Working session chats and reset, syntax help, desktop/mobile, keyboard and accessible loading/errors. No fake result or fake metrics. Product name Model Router. Remove irrelevant stub navigation and personal identity. Use textContent for untrusted values. No external runtime resources, no build step. Treat math formula display as readable plain text using a math font unless a local safe renderer is justified.
