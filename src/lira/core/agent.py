"""ReAct Agent implementation for L.I.R.A.

The agent uses a Reason + Act loop to autonomously handle user requests,
with self-correction capabilities for SQL errors and edge cases.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import Field

from lira.core.tools import ToolRegistry, ToolResult

if TYPE_CHECKING:
    from lira.core.tools import Tool

logger = logging.getLogger(__name__)


class AgentState(str, Enum):
    """Agent execution states."""

    IDLE = "idle"
    REASONING = "reasoning"
    ACTING = "acting"
    WAITING_INPUT = "waiting_input"
    ERROR = "error"
    COMPLETE = "complete"


@dataclass
class AgentConfig:
    """Configuration for the L.I.R.A. agent."""

    model: str = Field(default="gpt-4", description="LLM model to use")
    max_iterations: int = Field(default=10, description="Max ReAct loop iterations")
    temperature: float = Field(default=0.7, description="LLM temperature")
    timeout: int = Field(default=30, description="Tool execution timeout (seconds)")
    enable_self_correction: bool = Field(
        default=True, description="Enable automatic self-correction"
    )
    system_prompt: str | None = Field(default=None, description="Custom system prompt")

    @property
    def default_system_prompt(self) -> str:
        """Default system prompt for the agent."""
        return """You are L.I.R.A., an AI assistant for personal finance management.

Your capabilities:
- Execute SQL queries to fetch and modify financial data
- Fetch real-time stock quotes and financial data
- Generate visualizations and analytics
- Calculate portfolio metrics and tax implications

Always:
- Validate user input before processing
- Explain your reasoning before taking actions
- Confirm destructive operations with the user
- Prioritize data safety and security

When executing SQL:
- Use parameterized queries to prevent SQL injection
- Show the user what data will be affected
- Handle empty results gracefully
"""


@dataclass
class AgentResponse:
    """Response from agent execution."""

    state: AgentState
    message: str
    data: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    iterations: int = 0


class LLMProvider(Protocol):
    """Protocol for LLM providers."""

    def complete(self, prompt: str, **kwargs: Any) -> str:
        """Generate a completion."""
        ...

    async def acomplete(self, prompt: str, **kwargs: Any) -> str:
        """Generate an async completion."""
        ...


class Agent:
    """ReAct agent for autonomous financial management.

    The agent follows a Reason + Act loop:
    1. Think: Analyze the user's request
    2. Plan: Determine which tools to use
    3. Act: Execute tool calls
    4. Observe: Process results
    5. Loop: Continue until completion or max iterations
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        tool_registry: ToolRegistry | None = None,
        llm_provider: LLMProvider | None = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.tool_registry = tool_registry
        self.llm_provider = llm_provider
        self._state = AgentState.IDLE
        self._history: list[dict[str, Any]] = []

    @property
    def state(self) -> AgentState:
        """Current agent state."""
        return self._state

    def reset(self) -> None:
        """Reset agent state and history."""
        self._state = AgentState.IDLE
        self._history.clear()

    def register_tool(self, tool: Tool) -> None:
        """Register a tool with the agent."""
        if self.tool_registry is None:
            from lira.core.tools import ToolRegistry

            self.tool_registry = ToolRegistry()
        self.tool_registry.register(tool)

    async def run(self, user_input: str) -> AgentResponse:
        """Run the agent with user input.

        Args:
            user_input: Natural language request from user

        Returns:
            AgentResponse with results and state
        """
        self.reset()
        self._state = AgentState.REASONING

        iterations = 0
        max_iterations = self.config.max_iterations

        while iterations < max_iterations:
            iterations += 1

            try:
                if self._state == AgentState.REASONING:
                    plan = await self._reason(user_input)
                    if plan["action"] == "respond":
                        self._state = AgentState.COMPLETE
                        return AgentResponse(
                            state=AgentState.COMPLETE,
                            message=plan["message"],
                            data=plan.get("data"),
                            iterations=iterations,
                        )
                    if plan["action"] == "tool":
                        self._state = AgentState.ACTING

                elif self._state == AgentState.ACTING:
                    plan = getattr(self, "_current_plan", None)
                    if not plan:
                        self._state = AgentState.ERROR
                        return AgentResponse(
                            state=AgentState.ERROR,
                            message="No plan available for action",
                            iterations=iterations,
                        )
                    result = await self._act(plan["tool"], plan["args"])
                    self._history.append({"role": "tool", "tool": plan["tool"], "result": result})

                    if result.error:
                        if self.config.enable_self_correction:
                            user_input = self._construct_correction_prompt(
                                result.error, plan["tool"]
                            )
                            self._state = AgentState.REASONING
                        else:
                            self._state = AgentState.ERROR
                            return AgentResponse(
                                state=AgentState.ERROR,
                                message=f"Tool execution failed: {result.error}",
                                error=result.error,
                                iterations=iterations,
                            )
                    else:
                        self._state = AgentState.REASONING
                        user_input = f"Continue analysis with this result: {result.data}"
                        self._current_plan = plan if plan["action"] == "tool" else None

            except Exception as e:
                logger.exception("Agent error during iteration %d", iterations)
                self._state = AgentState.ERROR
                return AgentResponse(
                    state=AgentState.ERROR,
                    message=str(e),
                    error=str(e),
                    iterations=iterations,
                )

        return AgentResponse(
            state=AgentState.COMPLETE,
            message="Max iterations reached",
            iterations=iterations,
        )

    async def _reason(self, user_input: str) -> dict[str, Any]:
        """Reason about the next action to take.

        This is a placeholder for LLM-powered reasoning.
        """
        if self.llm_provider:
            prompt = self._build_reasoning_prompt(user_input)
            response = await self.llm_provider.acomplete(prompt)
            return self._parse_llm_response(response)

        return {
            "action": "respond",
            "message": "Agent reasoning not implemented. Provide LLM provider.",
        }

    def _build_reasoning_prompt(self, user_input: str) -> str:
        """Build prompt for reasoning."""
        system = self.config.system_prompt or self.config.default_system_prompt
        tools = self.tool_registry.list_tools() if self.tool_registry else []
        history = "\n".join(
            f"- {h['role']}: {h.get('tool', 'N/A')} -> {h.get('result', {}).get('data', 'N/A')}"
            for h in self._history[-3:]
        )

        return f"""{system}

Available tools:
{chr(10).join(f"- {t}" for t in tools)}

Recent history:
{history}

User request: {user_input}

What should I do? Respond with:
1. action: "tool" or "respond"
2. If tool: tool_name and arguments
3. If respond: message and optional data
"""

    def _parse_llm_response(self, response: str) -> dict[str, Any]:
        """Parse LLM response into action plan."""
        return {
            "action": "respond",
            "message": response,
        }

    async def _act(self, tool_name: str, args: dict[str, Any]) -> ToolResult:
        """Execute a tool action."""
        if not self.tool_registry:
            return ToolResult(
                success=False,
                error="No tools registered",
            )

        tool = self.tool_registry.get(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {tool_name}",
            )

        return await tool.execute(**args)

    def _construct_correction_prompt(self, error: str, failed_tool: str) -> str:
        """Construct a prompt for self-correction after error."""
        return f"""Previous tool '{failed_tool}' failed with error:
{error}

Please analyze the error and suggest a corrected approach.
Consider:
1. What went wrong?
2. How can we fix the input/parameters?
3. Should we try a different tool or approach?

Provide corrected tool call or respond directly to the user.
"""


class DummyLLMProvider:
    """Dummy LLM provider for testing."""

    async def acomplete(self, prompt: str, **kwargs: Any) -> str:
        return "I need more context to complete this request."

    def complete(self, prompt: str, **kwargs: Any) -> str:
        return "I need more context to complete this request."
