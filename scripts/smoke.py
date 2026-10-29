"""Exercise the real HTTP server on a temporary local port, then stop it."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = os.environ.copy()
    # Smoke verification never uses a provider key.
    environment.pop("AI_API_KEY", None)
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=20) as client:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError("Server exited before its health check")
                try:
                    if client.get("/api/health").status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Server did not become healthy")
            homepage = client.get("/")
            assert homepage.status_code == 200 and "AI Math Assistant" in homepage.text
            cases = [
                ({"operation": "derivative", "expression": "x^3"}, "3*x**2"),
                ({"operation": "integral", "expression": "2*x"}, "x**2"),
                ({"operation": "limit", "expression": "sin(x)/x", "target": "0"}, "1"),
                ({"operation": "equation", "expression": "x-2=0"}, "{2}"),
            ]
            for request, expected in cases:
                response = client.post("/api/solve", json=request)
                response.raise_for_status()
                data = response.json()
                assert data["status"] == "solved", data
                assert data["metrics"]["ai_calls"] == 0, data
                assert data["result"] == expected, (expected, data)
                print(f"PASS {request['operation']}: {data['result']}")
            rejected = client.post("/api/solve", json={"operation": "derivative", "expression": "__import__('os')"})
            assert rejected.status_code == 422, rejected.text
            assert client.get("/.env").status_code == 404
            print("PASS unsafe input rejected and secrets not served")
            with tempfile.TemporaryDirectory(prefix="math-evaluation-") as temporary:
                report_path = Path(temporary) / "report.json"
                subprocess.run(
                    [sys.executable, "-m", "benchmarks.run_benchmark", "--base-url",
                     str(client.base_url).rstrip("/"), "--output", str(report_path)],
                    cwd=ROOT, check=True, stdout=subprocess.DEVNULL,
                )
                report = json.loads(report_path.read_text(encoding="utf-8"))
                failures = []
                for case in report["cases"]:
                    for trial in case["solver"]["runs"]:
                        if not trial["score"]["passed"]:
                            failures.append(f"{case['id']}: {trial['score']['reason']}")
                        if (trial.get("body") or {}).get("metrics", {}).get("ai_calls") != 0:
                            failures.append(f"{case['id']}: missing zero-call routing evidence")
                assert not failures, "Frozen evaluation failed: " + "; ".join(failures)
                print("PASS all 40 frozen evaluation cases and zero-call routing")
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()


if __name__ == "__main__":
    main()
