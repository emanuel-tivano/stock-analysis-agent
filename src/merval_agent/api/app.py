import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from pydantic import Field

from merval_agent.bootstrap import build_agent
from merval_agent.config import Settings
from merval_agent.domain.models import FinalAnalysis, Model


class RunRequest(Model):
    message: str = Field(min_length=1, max_length=2000, pattern=r"\S")
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

    @app.get("/health")
    def health(request: Request):
        return {"status": "ok", "phase": 1, "llm_provider": request.app.state.provider}

    @app.post("/agent/run", response_model=FinalAnalysis)
    def run(body: RunRequest, request: Request):
        return request.app.state.agent.run(body.message, body.session_id)

    return app


app = create_app()
