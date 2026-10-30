# AI Math Assistant

A chat-style math website for derivatives, integrals, limits, and simple real polynomial equations. Supported calculations use SymPy with zero general-model calls. Students can explicitly request an AI explanation or fallback when a provider is configured.

The check label describes the evidence available for each answer. Numerical samples are not proofs. AI text is unverified. See the [implementation spec](docs/spec.md) for the supported boundary.

## Run locally

Python 3.14 is the tested runtime. Node.js runs the frontend behavior tests and JavaScript syntax checks.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c requirements.lock -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [AI Math Assistant locally](http://127.0.0.1:8000). Choose an operation, enter a formula in the visual editor, and submit. If the editor library is unavailable, the page provides a plain typed formula field, where multiplication must be explicit, such as `2*x`. Help in the website lists the supported grammar.

Choose **Edit question** beneath an answer or error to restore that question to the composer, including integral bounds or limit direction. Change it and submit to create a new attempt while retaining the original in the session. Editing alone makes no solver or AI call.

Useful demo shortcuts: press `/` from the page to focus the math composer, `Ctrl+K` on Windows or `Cmd+K` on macOS to search the session chats, and `Escape` to close the mobile sidebar or cancel an active request.

## Try the worked examples

1. Open **Worked examples** in the sidebar, or **Explore worked examples** on the welcome screen.
2. Choose **Substitution** or **Integration by parts**. Selection fills the composer without making a request.
3. Press **Solve**. Read the exact result, numbered steps, check status, and model-call count.
4. Open **Worked examples** again and choose **Definite integral**. Both bounds are filled for you.
5. Try **A limit that does not exist** or **Real-domain check** to see why the exact route stops safely.

Explanations from an AI provider remain optional. The worked steps for recognized rules use deterministic calculations. These are educational derivations, not a trace of every internal SymPy operation.

Open **Why this route?** to inspect this session's question outcomes, check types, and model usage. **Copy session evidence** and **Download session evidence** include the same summary before the detailed answers. The counts describe session activity and current question outcomes, rather than benchmark accuracy. Unknown provider usage stays unreported.

## Check before a direct merge

```powershell
.\.venv\Scripts\python.exe scripts/check.py
```

The local gate runs public API tests, JavaScript syntax checks, and real HTTP checks of all four operations and the 40 frozen evaluation cases. It fails if any expected outcome is wrong or zero-call routing evidence is missing. Provider contract tests use a fake external transport and make no paid calls. Browser journey evidence is recorded separately in [delivery validation](docs/delivery-validation.md).

## Connect an optional model provider

Create an untracked `.env` file or set these variables in your shell or deployment secret store: `AI_BASE_URL` should point to your provider's API base ending at its version prefix, `AI_MODEL` should name an accessible model, and `AI_API_KEY` should contain your key. The adapter appends `/chat/completions`. Confirm your provider supports the documented non-streaming request and usage fields.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --env-file .env --host 127.0.0.1 --port 8000
```

Keep `.env` out of Git. Exact math works without this configuration. Explain and Ask AI actions show unavailable until a provider is configured. The browser receives no provider key. [Provider research](docs/research/provider.md) records compatibility limits.

To reproduce an explanation followed by a failed retry without a live model, run `python scripts/preview_ai_contract.py`. Open the printed local URL, solve a question, and request an explanation twice. The first response and its token counters are explicitly labeled synthetic fixtures; later provider attempts fail. This preview binds only to localhost and substitutes the external HTTP transport. It does not measure model quality, usage, or efficiency.

## Evaluate the compute-saving claim

Use the [evaluation guide](docs/evaluation.md) to run the frozen 40-case set against the running HTTP server. Solver-only mode checks correctness and zero-call routing. Live comparison requires explicit opt-in and a configured provider. It can incur API charges.

Report model calls and provider-reported tokens separately from latency. The project does not measure energy, FLOPs, or total cloud compute. Do not describe a no-key run as evidence of equal AI quality or an AI speedup.

## Deploy manually

Use the [manual deployment guide](docs/deploy.md). No GitHub Actions are required. Keep the demo private while a billable provider is connected because this prototype has no multi-user authentication or per-user quota system.

The working application is under `app/` and `web/`. Local scratch work is ignored and is not part of the public source tree.

## Visual equation editor

The composer uses a bundled MathQuill editor for expressions, bounds, and limit targets. Type fractions, exponents, roots, trigonometric functions, and symbols visually. The browser converts the MathQuill LaTeX into the same bounded structured expression grammar used by the exact solver. The editor is a presentation layer only. It does not expand the solver's supported mathematics, and it never sends raw LaTeX to the API.

MathQuill is included under the Mozilla Public License. See `web/assets/LICENSES.txt` for third-party notices.
