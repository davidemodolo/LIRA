"""FastAPI application for L.I.R.A.

This module provides the main entry point for the REST API,
which is mostly used for the agentic loop communication layer.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from lira.core.agent import AgentConfig, AgentState, get_agent
from lira.db.session import DatabaseSession, init_database
from lira.version import __version__

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterator

    from sqlalchemy.orm import Session

from lira.api.routes import dashboard as dashboard_routes
from lira.api.routes import plots as plots_routes
from lira.api.ws import manager as ws_manager

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
# Suppress noisy third-party loggers
for _noisy in ("httpx", "httpcore", "sqlalchemy.engine", "yfinance", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# Basic Pydantic models for the chat
class ChatMessage(BaseModel):
    role: str
    content: str


class AgentChatRequest(BaseModel):
    messages: list[ChatMessage]
    agent_id: str | None = None
    stream: bool = False


class ConfirmRequest(BaseModel):
    pending_tool_calls: list[dict[str, Any]]
    stream: bool = True


class AgentChatResponse(BaseModel):
    message: ChatMessage
    final_state: str
    usage: dict[str, Any]


# Dependency for DB sessions
def get_db() -> Iterator[Session]:
    with DatabaseSession() as session:
        yield session


# Initialize application
init_database()


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """Store the running event loop on startup so WebSocket broadcasts work."""
    ws_manager._loop = asyncio.get_running_loop()
    yield


app = FastAPI(
    title="L.I.R.A. API",
    description="Agentic framework for L.I.R.A. running via fastmcp",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard_routes.router)
app.include_router(plots_routes.router)


@app.get("/dashboard", tags=["web"])
async def serve_dashboard() -> FileResponse:
    """Serve the dashboard web UI."""
    import os

    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return FileResponse(os.path.join(base_path, "web", "templates", "dashboard.html"))


@app.get("/", tags=["system"])
async def root() -> dict[str, str]:
    """Root endpoint - redirect to dashboard."""
    return {
        "name": "L.I.R.A. API",
        "version": __version__,
        "status": "online",
        "agentic": "true",
        "dashboard": "/dashboard",
    }


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time dashboard updates.

    The dashboard connects here and receives `data_changed` events whenever
    a mutation (transaction, investment, etc.) is committed on the server.
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep the connection alive; client sends periodic pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


@app.post("/api/chat", response_model=AgentChatResponse, tags=["agent"])
async def chat_with_agent(request: AgentChatRequest) -> Any:
    """Chat with the L.I.R.A. agent."""
    if not request.messages:
        raise HTTPException(status_code=400, detail="Messages list cannot be empty")

    prompt = request.messages[-1].content
    history = (
        [{"role": m.role, "content": m.content} for m in request.messages[:-1]]
        if len(request.messages) > 1
        else None
    )
    agent = get_agent(AgentConfig())

    try:
        if request.stream:

            async def generate() -> AsyncGenerator[str, None]:
                import json
                from dataclasses import asdict

                mutated = False
                async for event in agent.run_stream(prompt, history):
                    yield json.dumps(asdict(event)) + "\n"
                    if event.kind == "tool_result":
                        mutated = True
                if mutated:
                    await ws_manager.broadcast({"type": "data_changed"})

            return StreamingResponse(generate(), media_type="application/x-ndjson")

        trace_events: list[dict[str, Any]] = []
        mutated = False

        async for event in agent.run_stream(prompt, history):
            if event.kind in {"status", "tool_call", "tool_result", "llm_token"}:
                trace_events.append(
                    {
                        "kind": event.kind,
                        "content": event.content,
                        "payload": event.payload,
                    }
                )
            if event.kind == "tool_result":
                mutated = True

        result = await agent.run(prompt, history)

        if mutated:
            await ws_manager.broadcast({"type": "data_changed"})

        return AgentChatResponse(
            message=ChatMessage(role="assistant", content=result.message),
            final_state=result.state,
            usage={"iterations": result.iterations, "trace": trace_events},
        )
    except Exception as e:
        logger.exception("Agent run failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        await agent.llm_provider.close()


def main() -> None:
    """Entry point for the ``lira-api`` CLI command."""
    import uvicorn

    from lira.core.config import settings

    host = getattr(settings, "api_host", "0.0.0.0")
    port = getattr(settings, "api_port", 8001)
    reload = getattr(settings, "api_reload", False)
    uvicorn.run("lira.api.main:app", host=host, port=port, reload=reload)


@app.post("/api/chat/confirm", tags=["agent"])
async def confirm_mutations(request: ConfirmRequest) -> Any:
    """Execute previously previewed and confirmed mutation tool calls.

    Called by the frontend after the user clicks 'Confirm' on a HITL diff preview.
    Executes the tool calls directly without re-calling the LLM.
    """
    if not request.pending_tool_calls:
        raise HTTPException(status_code=400, detail="No pending tool calls to confirm")

    agent = get_agent(AgentConfig())

    try:
        if request.stream:

            async def generate() -> AsyncGenerator[str, None]:
                import json
                from dataclasses import asdict

                async for event in agent.run_confirmed(request.pending_tool_calls):
                    yield json.dumps(asdict(event)) + "\n"

            return StreamingResponse(generate(), media_type="application/x-ndjson")

        results: list[dict[str, Any]] = []
        final_message = ""
        async for event in agent.run_confirmed(request.pending_tool_calls):
            if event.kind == "tool_result":
                results.append(event.payload)
            elif event.kind == "final":
                resp = event.payload.get("response")
                if resp:
                    final_message = resp.message

        if results:
            await ws_manager.broadcast({"type": "data_changed"})

        return AgentChatResponse(
            message=ChatMessage(role="assistant", content=final_message),
            final_state=AgentState.COMPLETE,
            usage={"tool_results": results},
        )
    except Exception as e:
        logger.exception("Confirm mutations failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        await agent.llm_provider.close()
