# AI Math Assistant

A chat-style math website for derivatives, integrals, limits, and simple real polynomial equations. Supported calculations use SymPy with zero general-model calls. Students can explicitly request an AI explanation or fallback when a provider is configured.

The check label describes the evidence available for each answer. Numerical samples are not proofs. AI text is unverified. See the [implementation spec](docs/spec.md) for the supported boundary.

## Run locally

Python 3.14 is the tested runtime. Node.js is used only to check JavaScript syntax.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c requirements.lock -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [AI Math Assistant locally](http://127.0.0.1:8000). Choose an operation, enter a typed formula such as `x^3*sin(x)`, and submit. Use explicit multiplication. Help in the website lists the grammar.

Useful demo shortcuts: press `/` from the page to focus the math composer, `Ctrl+K` on Windows or `Cmd+K` on macOS to search the session chats, and `Escape` to close the mobile sidebar or cancel an active request.

## Check before a direct merge

```powershell
.\.venv\Scripts\python.exe scripts/check.py
```

The local gate runs public API tests, JavaScript syntax checks, and real HTTP checks of all four operations and the 40 frozen evaluation cases. It fails if any expected outcome is wrong or zero-call routing evidence is missing. Provider contract tests use a fake external transport and make no paid calls. Browser journey evidence is recorded separately in [delivery validation](docs/delivery-validation.md).

## Connect an optional model provider

Copy `.env.example` to `.env`. Set `AI_BASE_URL` to your provider's API base ending at its version prefix, `AI_MODEL` to an accessible model, and `AI_API_KEY` to your key. The adapter appends `/chat/completions`. Confirm your provider supports the documented non-streaming request and usage fields.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --env-file .env --host 127.0.0.1 --port 8000
```

Keep `.env` out of Git. Exact math works without this configuration. Explain and Ask AI actions show unavailable until a provider is configured. The browser receives no provider key. [Provider research](docs/research/provider.md) records compatibility limits.

## Evaluate the compute-saving claim

Use the [evaluation guide](docs/evaluation.md) to run the frozen 40-case set against the running HTTP server. Solver-only mode checks correctness and zero-call routing. Live comparison requires explicit opt-in and a configured provider. It can incur API charges.

Report model calls and provider-reported tokens separately from latency. The project does not measure energy, FLOPs, or total cloud compute. Do not describe a no-key run as evidence of equal AI quality or an AI speedup.

## Deploy manually

Use the [manual deployment guide](docs/deploy.md). No GitHub Actions are required. Keep the demo private while a billable provider is connected because this prototype has no multi-user authentication or per-user quota system.

The original visual exploration remains under `.scratch/ai-hackathon-environment/prototype/`. The working application is under `app/` and `web/`.
