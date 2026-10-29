"""FastAPI entry point for the local AI Math Assistant."""

from __future__ import annotations

import json
import os
import time
import asyncio
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .solver import GrammarError, SolveTimeout, SolveUnresolved, SolverBusy, run_bounded


class SolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["derivative", "integral", "limit", "equation"]
    expression: str = Field(min_length=1, max_length=400)
    variable: Literal["x"] = "x"
    lower: str | None = Field(default=None, max_length=100)
    upper: str | None = Field(default=None, max_length=100)
    target: str | None = Field(default=None, max_length=100)
    direction: Literal["both", "+", "-"] | None = None


app = FastAPI(title="AI Math Assistant", version="0.1.0")


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    content: dict[str, object] = {"error": "invalid_request", "detail": json.loads(json.dumps(exc.errors(), default=str))}
    if request.url.path == "/api/solve":
        content["metrics"] = {"route": "validation", "ai_calls": 0, "model_calls": 0, "solver_ms": None, "elapsed_ms": None, "model": None, "input_tokens": None, "output_tokens": None, "total_tokens": None}
    return JSONResponse(status_code=422, content=content)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if request.url.path != "/api/solve" or exc.status_code not in {400, 422}:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)
    content = dict(exc.detail) if isinstance(exc.detail, dict) else {"detail": exc.detail}
    content.setdefault("metrics", {"route": "validation", "ai_calls": 0, "model_calls": 0, "solver_ms": None, "elapsed_ms": None, "model": None, "input_tokens": None, "output_tokens": None, "total_tokens": None})
    return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)


@app.middleware("http")
async def limit_request_body(request: Request, call_next):
    content_length = request.headers.get("content-length")
    try:
        too_large = content_length is not None and int(content_length) > 16 * 1024
    except ValueError:
        too_large = True
    if too_large:
        content: dict[str, object] = {"error": "request_too_large", "detail": "Request body is limited to 16 KiB."}
        if request.url.path == "/api/solve":
            content["metrics"] = {"route": "validation", "ai_calls": 0, "model_calls": 0, "solver_ms": None, "elapsed_ms": None, "model": None, "input_tokens": None, "output_tokens": None, "total_tokens": None}
        return JSONResponse(status_code=413, content=content)
    if request.method in {"POST", "PUT", "PATCH"}:
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 16 * 1024:
                content = {"error": "request_too_large", "detail": "Request body is limited to 16 KiB."}
                if request.url.path == "/api/solve":
                    content["metrics"] = {"route": "validation", "ai_calls": 0, "model_calls": 0, "solver_ms": None, "elapsed_ms": None, "model": None, "input_tokens": None, "output_tokens": None, "total_tokens": None}
                return JSONResponse(status_code=413, content=content)
            body.extend(chunk)
        request._body = bytes(body)
    return await call_next(request)


@app.get("/api/health")
def health() -> dict[str, object]:
    configured = all(os.getenv(name) for name in ("AI_BASE_URL", "AI_API_KEY", "AI_MODEL"))
    return {"status": "ok", "ai_configured": configured}


def validate_solve_request(request: SolveRequest) -> dict[str, object]:
    payload = request.model_dump()
    operation = request.operation
    if operation == "integral":
        if (request.lower is None) != (request.upper is None):
            raise HTTPException(status_code=422, detail="Integral bounds must be provided together.")
        if request.target is not None or request.direction is not None:
            raise HTTPException(status_code=422, detail="Integral requests do not accept a limit target or direction.")
    elif operation == "limit":
        if request.target is None:
            raise HTTPException(status_code=422, detail="A limit target is required.")
        if request.lower is not None or request.upper is not None:
            raise HTTPException(status_code=422, detail="Limits do not accept integral bounds.")
    elif operation == "derivative":
        if any(value is not None for value in (request.lower, request.upper, request.target, request.direction)):
            raise HTTPException(status_code=422, detail="Derivatives accept only an expression and variable.")
    elif operation == "equation":
        if any(value is not None for value in (request.lower, request.upper, request.target, request.direction)):
            raise HTTPException(status_code=422, detail="Equations accept only an expression and variable.")
    return payload


def _unresolved(payload: dict[str, object], reason: str, note: str, started: float) -> dict[str, object]:
    elapsed = (time.perf_counter() - started) * 1000
    return {"status": "unresolved", "operation": payload["operation"], "expression": payload["expression"], "result": None, "latex": None, "verification": {"status": "not_checked", "method": reason, "detail": note}, "notes": [note], "metrics": {"route": "solver", "ai_calls": 0, "solver_ms": None, "elapsed_ms": round(elapsed, 3), "model": None, "input_tokens": None, "output_tokens": None, "total_tokens": None}, "request": payload}


def _solve_request_sync(request: SolveRequest) -> dict[str, object]:
    payload = validate_solve_request(request)
    started = time.perf_counter()
    try:
        outcome = run_bounded(payload)
    except GrammarError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SolverBusy as exc:
        raise HTTPException(status_code=503, detail="The exact solver is busy. Try again shortly.") from exc
    except SolveTimeout:
        return _unresolved(payload, "timeout", "The exact solver reached its time limit.", started)
    except SolveUnresolved as exc:
        return _unresolved(payload, "unresolved", str(exc), started)
    except Exception:
        return _unresolved(payload, "unresolved", "The exact solver could not safely finish this request.", started)
    elapsed = (time.perf_counter() - started) * 1000
    metrics = {"route": "solver", "ai_calls": 0, "solver_ms": outcome.get("solver_ms"), "elapsed_ms": round(elapsed, 3), "model": None, "input_tokens": None, "output_tokens": None, "total_tokens": None}
    return {"status": "solved", "operation": request.operation, "expression": request.expression, "result": outcome["result"], "latex": outcome["latex"], "verification": outcome["verification"], "notes": outcome.get("notes", []), "metrics": metrics, "request": payload}


@app.post("/api/solve")
async def solve(request: SolveRequest) -> dict[str, object]:
    return await solve_request(request)


async def solve_request(request: SolveRequest) -> dict[str, object]:
    """Run one exact solve without blocking an async caller."""
    return await asyncio.to_thread(_solve_request_sync, request)


static_root = Path(__file__).resolve().parent.parent / "web"
if static_root.is_dir():
    app.mount("/web", StaticFiles(directory=static_root, html=False), name="web")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static_root / "index.html")
