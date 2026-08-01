"""FastAPI application entrypoint.

Errors from the service layer are mapped to HTTP status codes in one place so
routes stay free of try/except noise and the frontend always receives a JSON
body of the shape {"detail": "..."} it can display.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .db import SupabaseError, close_db
from .evaluation import EvaluationError
from .llm import LLMError, build_llm_client
from .prompt_service import PromptServiceError
from .routes import bugs, evaluation, health, prompts

logger = logging.getLogger("hitl")
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = settings.missing()
    if missing:
        # Warn instead of crashing so /health can explain what is wrong.
        logger.warning("Missing environment variables: %s", ", ".join(missing))
    app.state.llm_client = build_llm_client()
    try:
        yield
    finally:
        await app.state.llm_client.aclose()
        await close_db()


app = FastAPI(
    title="Human-in-the-Loop Prompt Improvement System",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(LLMError)
async def handle_llm_error(_: Request, exc: LLMError) -> JSONResponse:
    logger.warning("LLM error: %s", exc)
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(SupabaseError)
async def handle_supabase_error(_: Request, exc: SupabaseError) -> JSONResponse:
    logger.error("Supabase error: %s", exc)
    return JSONResponse(
        status_code=502, content={"detail": f"Database request failed: {exc.detail}"}
    )


@app.exception_handler(PromptServiceError)
async def handle_prompt_error(_: Request, exc: PromptServiceError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(EvaluationError)
async def handle_evaluation_error(_: Request, exc: EvaluationError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(RuntimeError)
async def handle_runtime_error(_: Request, exc: RuntimeError) -> JSONResponse:
    logger.error("Unhandled runtime error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": str(exc)})


app.include_router(health.router)
app.include_router(bugs.router)
app.include_router(prompts.router)
app.include_router(evaluation.router)
