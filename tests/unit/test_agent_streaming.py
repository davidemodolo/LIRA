"""Unit tests for agent streaming and runtime lifecycle behavior."""

from __future__ import annotations

from typing import Any, AsyncIterator

import pytest

from lira.core.agent import Agent, AgentConfig, AgentState
from lira.core.tools import Tool, ToolRegistry, ToolResult


class FakeLLMProvider:
    """Simple fake LLM provider that yields predefined chunks."""

    def __init__(self, call_chunks: list[list[str]]) -> None:
        self.call_chunks = call_chunks
        self.prompts: list[str] = []

    async def astream_complete(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        self.prompts.append(prompt)
        call_index = min(len(self.prompts) - 1, len(self.call_chunks) - 1)
        for chunk in self.call_chunks[call_index]:
            yield chunk


class EchoTool(Tool):
    """Test tool that returns the input text."""

    name = "echo"
    description = "Echo back text"

    async def execute(self, text: str = "", **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, data={"text": text})

    def get_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
            },
            "required": [],
        }


@pytest.mark.asyncio
async def test_run_stream_returns_plain_text_response() -> None:
    """Agent should emit final plain-text response when no tool is requested."""
    provider = FakeLLMProvider([["Hello ", "world"]])
    registry = ToolRegistry()
    agent = Agent(
        config=AgentConfig(model="fake-model"),
        tool_registry=registry,
        llm_provider=provider,
    )

    response = await agent.run("hi")

    assert response.state == AgentState.COMPLETE
    assert response.message == "Hello world"


@pytest.mark.asyncio
async def test_run_stream_executes_tool_calls() -> None:
    """Agent should execute parsed tool calls and stream tool events."""
    provider = FakeLLMProvider(
        [
            ['{"tool_calls": [{"name": "echo", "arguments": {"text": "ciao"}}]}'],
        ]
    )
    registry = ToolRegistry()
    registry.register(EchoTool())

    agent = Agent(
        config=AgentConfig(model="fake-model"),
        tool_registry=registry,
        llm_provider=provider,
    )

    events = [event async for event in agent.run_stream("say ciao")]

    kinds = [event.kind for event in events]
    assert "tool_call" in kinds
    assert "tool_result" in kinds
    assert kinds[-1] == "final"
    assert "text: ciao" in events[-1].content


def test_default_provider_is_not_shared_between_agents() -> None:
    """Each Agent instance should own an independent provider by default."""
    first = Agent()
    second = Agent()

    assert first.llm_provider is not second.llm_provider


@pytest.mark.asyncio
async def test_agent_includes_previous_turns_in_next_prompt() -> None:
    """Second turn prompt should include prior user and assistant messages."""
    provider = FakeLLMProvider(
        [
            ["First answer"],
            ["Second answer"],
        ]
    )
    agent = Agent(
        config=AgentConfig(model="fake-model"),
        llm_provider=provider,
    )

    await agent.run("Do you have any account?")
    await agent.run("Show me transactions")

    assert len(provider.prompts) == 2
    second_prompt = provider.prompts[1]
    assert "User: Do you have any account?" in second_prompt
    assert "Assistant: First answer" in second_prompt
