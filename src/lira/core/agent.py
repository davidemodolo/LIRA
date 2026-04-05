"""ReAct Agent implementation for L.I.R.A.

The agent uses a Reason + Act loop to autonomously handle user requests,
with self-correction capabilities for SQL errors and edge cases.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from lira.core.config import settings
from lira.core.llm import LLMProvider, get_llm_provider
from lira.db.session import init_database
from lira.mcp.server import mcp

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class AgentState:
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

    max_iterations: int = field(default_factory=lambda: settings.agent_max_iterations)
    temperature: float = field(default_factory=lambda: settings.agent_temperature)
    timeout: int | None = field(default_factory=lambda: settings.agent_timeout)
    max_context_tokens: int = field(
        default_factory=lambda: settings.agent_max_context_tokens
    )
    enable_self_correction: bool = True
    history_turn_limit: int = 30


@dataclass
class AgentResponse:
    """Response from agent execution."""

    state: str
    message: str
    data: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    iterations: int = 0
    visualizations: list[str] = field(default_factory=list)


@dataclass
class AgentEvent:
    """Incremental event emitted while the agent is running."""

    kind: str
    content: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


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
        llm_provider: LLMProvider | None = None,
    ) -> None:
        self.config = config or AgentConfig()
        init_database()

        if llm_provider:
            self.llm_provider = llm_provider
        else:
            self.llm_provider = get_llm_provider()

        self._state = AgentState.IDLE
        self._history: list[dict[str, Any]] = []
        self._tools_schema = self._build_tools_schema()

    @property
    def state(self) -> str:
        """Get current agent state."""
        return self._state

    def _build_tools_schema(self) -> str:
        """Build tools description for system prompt."""
        tools_desc = []

        for tool in mcp._local_provider._components.values():
            if not hasattr(tool, "parameters"):
                continue
            tools_desc.append(f"- {tool.name}: {tool.description}")

            schema = tool.parameters or {}
            properties = (
                schema.get("properties", {}) if isinstance(schema, dict) else {}
            )
            required = (
                set(schema.get("required", [])) if isinstance(schema, dict) else set()
            )

            if properties:
                tools_desc.append("  args:")
                for arg_name, arg_schema in properties.items():
                    arg_info = arg_schema if isinstance(arg_schema, dict) else {}
                    arg_type = arg_info.get("type", "any")
                    arg_desc = arg_info.get("description", "")
                    req = "required" if arg_name in required else "optional"

                    parts = [f"{arg_name} ({arg_type}, {req})"]
                    if "default" in arg_info:
                        parts.append(f"default={arg_info['default']}")
                    if "enum" in arg_info:
                        parts.append(f"enum={arg_info['enum']}")

                    header = ", ".join(parts)
                    if arg_desc:
                        tools_desc.append(f"    - {header}: {arg_desc}")
                    else:
                        tools_desc.append(f"    - {header}")

        return "\n".join(tools_desc)

    async def run(
        self,
        user_input: str,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> AgentResponse:
        """Run the agent with user input and return the final response.

        Args:
            user_input: Current user message
            conversation_history: Optional external conversation history
                                  (for stateless server mode)
        """
        final_response: AgentResponse | None = None

        async for event in self.run_stream(user_input, conversation_history):
            if event.kind in {"final", "error"}:
                final_response = event.payload.get("response")

        if final_response is None:
            self._state = AgentState.ERROR
            return AgentResponse(
                state=AgentState.ERROR,
                message="I encountered an unexpected runtime state.",
                error="missing final response",
            )

        return final_response

    async def run_stream(
        self,
        user_input: str,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run the agent and stream intermediate events.

        Args:
            user_input: Natural language user query.
            conversation_history: Optional external conversation history
                                  (for stateless server mode)

        Yields:
            AgentEvent values describing model output, tool calls, and final result.
        """
        self._state = AgentState.REASONING

        today = datetime.now(timezone.utc).date().isoformat()
        system_prompt = f"""You are L.I.R.A., an AI assistant for personal finance management.

Current date: {today}

Your capabilities:
- list_accounts: List all accounts with their balances
- create_account: Create a new financial account
- create_transaction: Record income or expenses
- get_transactions: View recent transactions
- generate_plot: Create visualizations (bar, line, pie, scatter charts)

Available tools:
{self._tools_schema}

Instructions:
1. Parse the user's natural language request
2. If the user wants to see data, call the appropriate tool(s)
3. If creating a transaction, FIRST use list_accounts to find the correct account_id for the given account name.
4. If the user wants a chart or visualization, use generate_plot
5. Return results in a friendly format
6. If creating data, confirm with user first
7. Tool argument names must match the schema exactly (e.g. use transaction_type, not type)

IMPORTANT: When calling tools, respond ONLY with JSON like:
{{"tool_calls": [{{"name": "tool_name", "arguments": {{"arg1": "value1"}}}}]}}

If no tools needed, respond with plain text."""

        conversation = self._build_conversation(
            system_prompt=system_prompt,
            user_input=user_input,
            external_history=conversation_history,
        )

        estimated_tokens = len(conversation) // 4
        context_pct = min(
            100.0, (estimated_tokens / self.config.max_context_tokens) * 100
        )
        yield AgentEvent(
            kind="status",
            content=f"Analyzing request (Context filled: {context_pct:.1f}%)",
        )

        visualizations: list[str] = []

        iterations = 0
        resolved_calls: list[dict[str, Any]] = []

        while iterations < self.config.max_iterations:
            iterations += 1
            try:
                llm_chunks: list[str] = []
                async for chunk in self.llm_provider.astream_complete(
                    conversation,
                    temperature=self.config.temperature,
                ):
                    llm_chunks.append(chunk)
                    yield AgentEvent(kind="llm_token", content=chunk)

                response_text = self._clean_response("".join(llm_chunks))

                tool_calls = self._parse_tool_calls(response_text)
                if not tool_calls:
                    self._state = AgentState.COMPLETE
                    final_message = (
                        response_text or "I didn't understand that. Can you rephrase?"
                    )
                    response = AgentResponse(
                        state=AgentState.COMPLETE,
                        message=final_message,
                        iterations=iterations,
                        visualizations=visualizations,
                        tool_calls=resolved_calls,
                    )
                    self._append_history(
                        user_input=user_input, assistant_output=final_message
                    )
                    yield AgentEvent(
                        kind="final",
                        content=final_message,
                        payload={"response": response},
                    )
                    return

                self._state = AgentState.ACTING
                yield AgentEvent(kind="status", content="Executing tools")

                results: list[Any] = []
                for call in tool_calls:
                    tool_name = call["name"]
                    arguments = call["arguments"]
                    resolved_calls.append(call)

                    yield AgentEvent(
                        kind="tool_call",
                        payload={"name": tool_name, "arguments": arguments},
                    )

                    import json

                    try:
                        res = await mcp.call_tool(tool_name, arguments)
                        tool_data = ""
                        for content_item in res.content:
                            if content_item.type == "text":
                                tool_data += content_item.text

                        parsed_data = None

                        mcp_res = (
                            res.to_mcp_result()
                            if hasattr(res, "to_mcp_result")
                            else res
                        )
                        success = not getattr(mcp_res, "isError", False)
                        tool_error = tool_data if not success else None

                        if tool_error:
                            results.append(f"Error: {tool_error}")
                        else:
                            try:
                                parsed_data = json.loads(tool_data)
                            except json.JSONDecodeError:
                                parsed_data = tool_data

                            results.append(parsed_data)
                            if tool_name == "generate_plot" and isinstance(
                                parsed_data, dict
                            ):
                                img = parsed_data.get("image_base64")
                                if img:
                                    visualizations.append(img)

                        yield AgentEvent(
                            kind="tool_result",
                            payload={
                                "name": tool_name,
                                "success": success,
                                "error": tool_error,
                                "data": parsed_data,
                            },
                        )
                    except Exception as e:
                        error_text = f"Tool failure: {tool_name} - {e!s}"
                        results.append(error_text)
                        yield AgentEvent(
                            kind="tool_result",
                            payload={
                                "name": tool_name,
                                "success": False,
                                "error": error_text,
                                "data": None,
                            },
                        )
                        continue

                # Instead of returning COMPLETE here, we append tool results to the conversation
                # and loop again.
                tool_results_text = "Tool Results:\n" + self._format_results(results)
                conversation += f"\n\nAssistant (Tool call): {json.dumps({'tool_calls': tool_calls})}\n\nSystem: {tool_results_text}\n\nRespond with JSON tool call or plain text:"

            except Exception as e:
                logger.exception("Agent error")
                self._state = AgentState.ERROR
                message = f"I encountered an error: {e!s}"
                response = AgentResponse(
                    state=AgentState.ERROR,
                    message=message,
                    error=str(e),
                    visualizations=visualizations,
                )
                self._append_history(user_input=user_input, assistant_output=message)
                yield AgentEvent(
                    kind="error", content=message, payload={"response": response}
                )
                return

        # If we loop out
        self._state = AgentState.ERROR
        message = "Max iterations reached."
        response = AgentResponse(
            state=AgentState.ERROR,
            message=message,
            error="max_iterations",
            visualizations=visualizations,
        )
        self._append_history(user_input=user_input, assistant_output=message)
        yield AgentEvent(kind="error", content=message, payload={"response": response})

    def _build_conversation(
        self,
        system_prompt: str,
        user_input: str,
        external_history: list[dict[str, Any]] | None = None,
    ) -> str:
        """Build conversation text with recent history included.

        Args:
            system_prompt: System instructions for the model
            user_input: Current user message
            external_history: External conversation history (for stateless mode)

        Returns:
            Formatted conversation string
        """
        lines = [f"System: {system_prompt}", ""]

        if external_history:
            for entry in external_history[-self.config.history_turn_limit * 2 :]:
                role = entry.get("role", "assistant")
                label = "User" if role == "user" else "Assistant"
                content = str(entry.get("content", "")).strip()
                if not content:
                    continue
                lines.extend([f"{label}: {content}", ""])
        else:
            for entry in self._get_recent_history():
                role = entry.get("role", "assistant")
                label = "User" if role == "user" else "Assistant"
                content = str(entry.get("content", "")).strip()
                if not content:
                    continue
                lines.extend([f"{label}: {content}", ""])

        lines.extend(
            [
                f"User: {user_input}",
                "",
                "Respond with JSON tool call or plain text:",
            ]
        )
        return "\n".join(lines)

    def _append_history(self, user_input: str, assistant_output: str) -> None:
        """Append the latest turn to in-memory conversation history."""
        self._history.extend(
            [
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": assistant_output},
            ]
        )

        max_messages = max(self.config.history_turn_limit, 1) * 2
        if len(self._history) > max_messages:
            self._history = self._history[-max_messages:]

    def _get_recent_history(self) -> list[dict[str, Any]]:
        """Get bounded history entries included in each model call."""
        max_messages = max(self.config.history_turn_limit, 1) * 2
        if len(self._history) <= max_messages:
            return self._history
        return self._history[-max_messages:]

    def _parse_tool_calls(self, response_text: str) -> list[dict[str, Any]]:
        """Parse model output into normalized tool calls.

        Args:
            response_text: Model response that may contain tool call JSON.

        Returns:
            A normalized list of tool call dictionaries.
        """
        if "{" not in response_text:
            return []

        # Find the first { and the last }
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}")
        if start_idx == -1 or end_idx == -1 or start_idx > end_idx:
            return []

        json_str = response_text[start_idx : end_idx + 1]

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return []

        raw_calls = data.get("tool_calls")
        if not isinstance(raw_calls, list):
            return []

        parsed_calls: list[dict[str, Any]] = []
        for call in raw_calls:
            if not isinstance(call, dict):
                continue

            name = call.get("name")
            arguments = call.get("arguments", {})
            if not isinstance(name, str):
                continue
            if not isinstance(arguments, dict):
                arguments = {}

            parsed_calls.append({"name": name, "arguments": arguments})

        return parsed_calls

    def _format_results(self, results: list[Any]) -> str:
        """Format tool results for display."""
        if not results:
            return "No results found."

        formatted = []
        for result in results:
            if isinstance(result, list):
                for item in result:
                    formatted.append(f"- {item}")
            elif isinstance(result, dict):
                parts = [f"{k}: {v}" for k, v in result.items()]
                formatted.append(", ".join(parts))
            else:
                formatted.append(str(result))

        return "\n".join(formatted) if formatted else "Done."

    def _clean_response(self, response: str) -> str:
        """Clean up the LLM response."""
        response = response.strip()

        response = re.sub(r"^```[\w]*\n?", "", response)
        return re.sub(r"\n?```$", "", response)

    def reset(self) -> None:
        """Reset agent state and history."""
        self._state = AgentState.IDLE
        self._history.clear()
