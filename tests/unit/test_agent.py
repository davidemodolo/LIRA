"""Unit tests for Agent."""

import pytest

from lira.core.agent import Agent, AgentConfig, AgentState


@pytest.mark.asyncio
async def test_agent_initialization():
    """Test agent initialization."""
    config = AgentConfig(model="gpt-4", max_iterations=5)
    agent = Agent(config=config)

    assert agent.config.model == "gpt-4"
    assert agent.config.max_iterations == 5
    assert agent.state == AgentState.IDLE


@pytest.mark.asyncio
async def test_agent_reset():
    """Test agent reset."""
    agent = Agent()
    agent._state = AgentState.REASONING

    agent.reset()

    assert agent.state == AgentState.IDLE
    assert len(agent._history) == 0


@pytest.mark.asyncio
async def test_agent_run_without_llm():
    """Test agent run without LLM provider returns error message."""
    agent = Agent(config=AgentConfig())

    response = await agent.run("Show me my transactions")

    assert response.state == AgentState.COMPLETE
    assert "not implemented" in response.message.lower()


@pytest.mark.asyncio
async def test_agent_max_iterations():
    """Test agent respects max iterations."""
    config = AgentConfig(max_iterations=3, enable_self_correction=False)
    agent = Agent(config=config)

    response = await agent.run("Help me")

    assert response.iterations <= config.max_iterations


@pytest.mark.asyncio
async def test_agent_config_defaults():
    """Test agent config default values."""
    config = AgentConfig()

    assert config.model == "gpt-4"
    assert config.max_iterations == 10
    assert config.temperature == 0.7
    assert config.enable_self_correction is True


@pytest.mark.asyncio
async def test_agent_system_prompt():
    """Test agent system prompt."""
    custom_prompt = "You are a financial advisor."
    config = AgentConfig(system_prompt=custom_prompt)
    agent = Agent(config=config)

    assert agent.config.system_prompt == custom_prompt
    assert "financial advisor" in agent.config.default_system_prompt
