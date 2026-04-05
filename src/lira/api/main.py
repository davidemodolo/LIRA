"""FastAPI application for L.I.R.A.

This module provides the main entry point for the REST API,
which is mostly used for the agentic loop communication layer.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from lira.core.agent import Agent, AgentConfig
from lira.db.session import DatabaseSession, init_database
from lira.version import __version__

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterator

    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# Basic Pydantic models for the chat
class ChatMessage(BaseModel):
    role: str
    content: str


class AgentChatRequest(BaseModel):
    messages: list[ChatMessage]
    agent_id: str | None = None
    stream: bool = False


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

app = FastAPI(
    title="L.I.R.A. API",
    description="Agentic framework for L.I.R.A. running via fastmcp",
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Connect FastMCP to FastAPI app


@app.get("/", tags=["system"])
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "name": "L.I.R.A. API",
        "version": __version__,
        "status": "online",
        "agentic": "true",
    }


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/api/chat", response_model=AgentChatResponse, tags=["agent"])
async def chat_with_agent(request: AgentChatRequest) -> Any:
    """Chat with the L.I.R.A. agent."""
    if not request.messages:
        raise HTTPException(status_code=400, detail="Messages list cannot be empty")

    prompt = request.messages[-1].content
    agent = Agent(AgentConfig())

    try:
        if request.stream:

            async def generate() -> AsyncGenerator[str, None]:
                import json
                from dataclasses import asdict
                async for event in agent.run_stream(prompt):
                    yield json.dumps(asdict(event)) + "\n"

            return StreamingResponse(generate(), media_type="application/x-ndjson")

        result = await agent.run(prompt)
        return AgentChatResponse(
            message=ChatMessage(role="assistant", content=result),
            final_state=agent.state,
            usage={},
        )
    except Exception as e:
        logger.exception("Agent run failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        await agent.llm_provider.close()
