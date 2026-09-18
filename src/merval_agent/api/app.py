import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from merval_agent.bootstrap import build_agent
from merval_agent.config import Settings
from merval_agent.domain.models import FinalAnalysis, Model
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
