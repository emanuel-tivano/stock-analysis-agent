import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from merval_agent.bootstrap import build_agent
from merval_agent.config import Settings
from merval_agent.domain.actions import (
    ActionDecisionResponse,
    ApproveActionRequest,
    ModifyActionRequest,
    RejectActionRequest,
)
from merval_agent.domain.models import FinalAnalysis, Model
from merval_agent.memory.actions import ActionConflict, ActionNotFound
from merval_agent.presentation.models import ChatResponse
from merval_agent.presentation.presenter import present_analysis

WEB_DIR = Path(__file__).with_name("web")


class RunRequest(Model):
    message: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    session_id: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$"
    )


class ChatRequest(Model):
    message: str = Field(max_length=2000)
    session_id: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$"
    )


def create_app(agent=None, settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        logging.basicConfig(level=logging.INFO)
        config = settings or Settings()
        with httpx.Client(timeout=config.http_timeout_seconds, follow_redirects=True) as http:
            app.state.agent = agent or build_agent(config, http)
            app.state.provider = config.llm_provider
            yield

    app = FastAPI(title="Merval Equity Analyst AI", lifespan=lifespan)
    app.mount("/assets", StaticFiles(directory=WEB_DIR), name="web-assets")

    @app.exception_handler(Exception)
    async def unexpected_failure(request, exc):
        return JSONResponse(
            status_code=500,
            content={
                "detail": "No se pudo completar la operación. Consultá el estado antes de reintentar."
            },
        )

    @app.exception_handler(ActionNotFound)
    async def action_missing(request, exc):
        return JSONResponse(
            status_code=404, content={"detail": "Acción no encontrada para esta sesión."}
        )

    @app.exception_handler(ActionConflict)
    async def action_conflict(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(sqlite3.Error)
    async def storage_unavailable(request, exc):
        return JSONResponse(
            status_code=503,
            content={"detail": "No se pudo guardar la decisión. Reintentá con la misma clave."},
        )

    @app.get("/agent/actions/{action_id}", response_model=ActionDecisionResponse)
    def get_action(
        action_id: UUID,
        request: Request,
        session_id: str = Query(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"),
    ):
        return request.app.state.agent.repository.get_action(action_id, session_id)

    @app.get("/agent/actions/{action_id}/events")
    def action_events(
        action_id: UUID,
        request: Request,
        session_id: str = Query(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"),
    ):
        return request.app.state.agent.repository.get_action_events(action_id, session_id)

    @app.post("/agent/actions/{action_id}/approve", response_model=ActionDecisionResponse)
    def approve_action(action_id: UUID, body: ApproveActionRequest, request: Request):
        return request.app.state.agent.repository.decide_action(action_id, "approve", body)

    @app.post("/agent/actions/{action_id}/modify", response_model=ActionDecisionResponse)
    def modify_action(action_id: UUID, body: ModifyActionRequest, request: Request):
        return request.app.state.agent.repository.decide_action(action_id, "modify", body)

    @app.post("/agent/actions/{action_id}/reject", response_model=ActionDecisionResponse)
    def reject_action(action_id: UUID, body: RejectActionRequest, request: Request):
        return request.app.state.agent.repository.decide_action(action_id, "reject", body)

    @app.middleware("http")
    async def json_charset(request, call_next):
        response = await call_next(request)
        if response.headers.get("content-type", "").split(";")[0] == "application/json":
            response.headers["content-type"] = "application/json; charset=utf-8"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path == "/" or request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self'; connect-src 'self'; base-uri 'none'; "
                "form-action 'self'; frame-ancestors 'none'"
            )
        return response

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_DIR / "index.html", media_type="text/html")

    @app.get("/health")
    def health(request: Request):
        return {"status": "ok", "phase": 1, "llm_provider": request.app.state.provider}

    @app.post("/agent/run", response_model=FinalAnalysis)
    def run(body: RunRequest, request: Request):
        return request.app.state.agent.run(body.message, body.session_id)

    @app.post("/chat", response_model=ChatResponse)
    def chat(body: ChatRequest, request: Request):
        if not body.message.strip():
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "EMPTY_MESSAGE",
                        "message": "Escribí una consulta antes de enviarla.",
                    }
                },
            )

        try:
            result = request.app.state.agent.run(body.message, body.session_id)
            return present_analysis(result)
        except Exception:
            trace_id = str(uuid4())
            logging.getLogger("merval_agent").exception(
                "Unhandled chat presentation failure trace_id=%s", trace_id
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": (
                            "Ocurrió un error interno. "
                            f"Usá el identificador {trace_id} para reportarlo."
                        ),
                        "trace_id": trace_id,
                    }
                },
            )

    return app


app = create_app()
