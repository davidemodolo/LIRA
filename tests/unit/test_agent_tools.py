"""Unit tests for Agent tools including generate_plot."""

import pytest

from lira.core.agent import Agent, AgentConfig
from lira.core.tools import Tool, ToolRegistry


class TestGeneratePlotTool:
    """Tests for the generate_plot tool."""

    @pytest.fixture
    def agent_with_plot_tool(self):
        """Create agent with generate_plot tool."""
        config = AgentConfig()
        agent = Agent(config=config)
        return agent

    def test_generate_plot_tool_registered(self, agent_with_plot_tool):
        """Test that generate_plot tool is registered."""
        tool = agent_with_plot_tool.tool_registry.get("generate_plot")

        assert tool is not None
        assert tool.name == "generate_plot"

    def test_generate_plot_tool_schema(self, agent_with_plot_tool):
        """Test generate_plot tool schema."""
        tool = agent_with_plot_tool.tool_registry.get("generate_plot")
        schema = tool.get_schema()

        assert "properties" in schema
        assert "plot_type" in schema["properties"]
        assert "title" in schema["properties"]
        assert "data" in schema["properties"]

    @pytest.mark.asyncio
    async def test_generate_plot_bar_chart(self, agent_with_plot_tool):
        """Test generating a bar chart with real matplotlib."""
        tool = agent_with_plot_tool.tool_registry.get("generate_plot")

        result = await tool.execute(
            plot_type="bar",
            title="Monthly Spending",
            data=[
                {"category": "Groceries", "amount": 500},
                {"category": "Dining", "amount": 200},
                {"category": "Transport", "amount": 150},
            ],
            x_key="category",
            y_key="amount",
        )

        assert result.success is True
        assert "image_base64" in result.data
        assert len(result.data["image_base64"]) > 1000

    @pytest.mark.asyncio
    async def test_generate_plot_invalid_type(self, agent_with_plot_tool):
        """Test that invalid plot type returns error."""
        tool = agent_with_plot_tool.tool_registry.get("generate_plot")

        result = await tool.execute(
            plot_type="invalid",
            title="Test",
            data=[{"x": 1, "y": 2}],
        )

        assert result.success is False
        assert "Unsupported plot type" in result.error


class TestToolRegistry:
    """Tests for ToolRegistry."""

    def test_register_and_get_tool(self):
        """Test tool registration and retrieval."""
        registry = ToolRegistry()

        class TestTool(Tool):
            name = "test_tool"
            description = "A test tool"

            async def execute(self, **kwargs):
                pass

            def get_schema(self):
                return {}

        registry.register(TestTool())

        tool = registry.get("test_tool")
        assert tool is not None
        assert tool.name == "test_tool"

    def test_get_nonexistent_tool(self):
        """Test getting nonexistent tool returns None."""
        registry = ToolRegistry()

        tool = registry.get("nonexistent")
        assert tool is None

    def test_list_tools(self):
        """Test listing all registered tools."""
        registry = ToolRegistry()

        class Tool1(Tool):
            name = "tool1"
            description = ""

            async def execute(self, **kwargs):
                pass

            def get_schema(self):
                return {}

        class Tool2(Tool):
            name = "tool2"
            description = ""

            async def execute(self, **kwargs):
                pass

            def get_schema(self):
                return {}

        registry.register(Tool1())
        registry.register(Tool2())

        tools = registry.list_tools()

        assert "tool1" in tools
        assert "tool2" in tools
