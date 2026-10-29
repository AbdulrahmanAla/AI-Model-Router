# Deploy the demo manually

Run `python scripts/check.py` from the project virtual environment before you deploy. Freeze the Git commit you intend to demonstrate.

## Start without a model key

On a Python 3.14 host, run `python -m pip install -c requirements.lock -r requirements.txt` in a virtual environment. Copy `app/` and `web/`, then start:

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Use the hosting platform's HTTPS proxy and private demo access. Set its internal service port to 8000 and health-check path to `/api/health`. Do not serve the repository directory with a static file server.

## Use a container host

When Docker is available, build and run:

```powershell
docker build -t ai-math-assistant .
docker run --rm -p 8000:8000 ai-math-assistant
```

Set `AI_BASE_URL`, `AI_MODEL`, and `AI_API_KEY` in hosting secrets when you want live explanations. Use the same environment variable names as `.env.example`. Do not bake credentials into the image. Keep the deployment private when a billable provider is connected.

## Check the deployed URL

1. Open the HTTPS URL and submit `x^3` as a derivative. Expect `3*x**2` and zero AI calls.
2. Integrate `2*x`, find the limit of `sin(x)/x` at zero, and solve `x-2=0`.
3. Enter `__import__('os')`. Expect a grammar rejection.
4. Open route details. Check that timings come from this request.
5. With no provider key, click Explain. Expect a clear unavailable message and a preserved exact answer.
6. With a configured key, click Explain once. Confirm one attempt, a model name, and reported usage or unknown usage.
7. Verify `/.env` and `/docs/spec.md` are not exposed as files.

Record the URL, Git commit, provider/model if used, and the smoke-test outcomes. External hosting is complete only after these checks pass against that real URL. A local server or a Dockerfile alone is not an external deployment.
