"""ReAct Agent implementation for L.I.R.A.

The agent uses a Reason + Act loop to autonomously handle user requests,
with self-correction capabilities for SQL errors and edge cases.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from lira.core.llm import OllamaProvider
from lira.core.tools import Tool, ToolRegistry, ToolResult

logger = logging.getLogger(__name__)


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

    model: str = "gemma4:31b"
    max_iterations: int = 10
    temperature: float = 0.7
    timeout: int = 120
    enable_self_correction: bool = True
    ollama_base_url: str = "http://localhost:11434"
    ollama_keep_alive: str = "30m"
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
        tool_registry: ToolRegistry | None = None,
        llm_provider: OllamaProvider | None = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.tool_registry = tool_registry or self._create_default_registry()
        self.llm_provider = llm_provider or OllamaProvider(
            base_url=self.config.ollama_base_url,
            model=self.config.model,
            temperature=self.config.temperature,
            timeout=self.config.timeout,
            keep_alive=self.config.ollama_keep_alive,
        )
        self._state = AgentState.IDLE
        self._history: list[dict[str, Any]] = []
        self._tools_schema = self._build_tools_schema()

    @property
    def state(self) -> str:
        """Get current agent state."""
        return self._state

    def _create_default_registry(self) -> ToolRegistry:
        """Create default tool registry with CRUD operations."""
        from decimal import Decimal

        from lira.db.repositories import (
            AccountRepository,
            TransactionRepository,
        )
        from lira.db.session import DatabaseSession

        registry = ToolRegistry()

        class ListAccountsTool(Tool):
            name = "list_accounts"
            description = (
                "List all accounts. Returns account details including balance."
            )

            async def execute(self, **kwargs: Any) -> ToolResult:
                try:
                    with DatabaseSession() as session:
                        repo = AccountRepository(session)
                        accounts = repo.get_all()
                        return ToolResult(
                            success=True,
                            data=[
                                {
                                    "id": a.id,
                                    "name": a.name,
                                    "type": a.account_type.value,
                                    "balance": float(a.balance),
                                    "currency": a.currency,
                                }
                                for a in accounts
                            ],
                        )
                except Exception as e:
                    return ToolResult(success=False, error=str(e))

            def get_schema(self) -> dict[str, Any]:
                return {"type": "object", "properties": {}, "required": []}

        class CreateTransactionTool(Tool):
            name = "create_transaction"
            description = "Create a new transaction (income or expense)"

            async def execute(
                self,
                account_id: int,
                amount: float,
                transaction_type: str,
                description: str = "",
                **kwargs: Any,
            ) -> ToolResult:
                try:
                    with DatabaseSession() as session:
                        repo = TransactionRepository(session)
                        t = repo.create(
                            account_id=account_id,
                            transaction_type=transaction_type,
                            amount=Decimal(str(amount)),
                            description=description,
                        )
                        return ToolResult(
                            success=True,
                            data={
                                "id": t.id,
                                "amount": float(t.amount),
                                "type": t.transaction_type.value,
                            },
                        )
                except Exception as e:
                    return ToolResult(success=False, error=str(e))

            def get_schema(self) -> dict[str, Any]:
                return {
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "integer", "description": "Account ID"},
                        "amount": {
                            "type": "number",
                            "description": "Transaction amount",
                        },
                        "transaction_type": {
                            "type": "string",
                            "enum": ["income", "expense"],
                            "description": "Type of transaction",
                        },
                        "description": {"type": "string", "description": "Description"},
                    },
                    "required": ["account_id", "amount", "transaction_type"],
                }

        class GetTransactionsTool(Tool):
            name = "get_transactions"
            description = "Get recent transactions"

            async def execute(
                self, account_id: int | None = None, limit: int = 10, **kwargs: Any
            ) -> ToolResult:
                try:
                    with DatabaseSession() as session:
                        repo = TransactionRepository(session)
                        transactions = repo.get_all(account_id=account_id, limit=limit)
                        return ToolResult(
                            success=True,
                            data=[
                                {
                                    "id": t.id,
                                    "date": t.date.isoformat(),
                                    "amount": float(t.amount),
                                    "type": t.transaction_type.value,
                                    "description": t.description,
                                }
                                for t in transactions
                            ],
                        )
                except Exception as e:
                    return ToolResult(success=False, error=str(e))

            def get_schema(self) -> dict[str, Any]:
                return {
                    "type": "object",
                    "properties": {
                        "account_id": {
                            "type": "integer",
                            "description": "Account ID (optional)",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 10,
                            "description": "Max transactions to return",
                        },
                    },
                    "required": [],
                }

        class CreateAccountTool(Tool):
            name = "create_account"
            description = "Create a new account"

            async def execute(
                self,
                name: str,
                account_type: str = "checking",
                balance: float = 0.0,
                **kwargs: Any,
            ) -> ToolResult:
                try:
                    with DatabaseSession() as session:
                        repo = AccountRepository(session)
                        a = repo.create(
                            name=name,
                            account_type=account_type,
                            balance=Decimal(str(balance)),
                        )
                        return ToolResult(
                            success=True,
                            data={
                                "id": a.id,
                                "name": a.name,
                                "balance": float(a.balance),
                            },
                        )
                except Exception as e:
                    return ToolResult(success=False, error=str(e))

            def get_schema(self) -> dict[str, Any]:
                return {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Account name"},
                        "account_type": {
                            "type": "string",
                            "enum": [
                                "checking",
                                "savings",
                                "credit_card",
                                "investment",
                            ],
                            "default": "checking",
                        },
                        "balance": {
                            "type": "number",
                            "default": 0.0,
                            "description": "Initial balance",
                        },
                    },
                    "required": ["name"],
                }

        registry.register(ListAccountsTool())
        registry.register(CreateTransactionTool())
        registry.register(GetTransactionsTool())
        registry.register(CreateAccountTool())

        return registry

    def _build_tools_schema(self) -> str:
        """Build tools description for system prompt."""
        tools_desc = []
        for tool in self.tool_registry._tools.values():
            tools_desc.append(f"- {tool.name}: {tool.description}")

        return "\n".join(tools_desc)

    async def run(self, user_input: str) -> AgentResponse:
        """Run the agent with user input and return the final response."""
        final_response: AgentResponse | None = None

        async for event in self.run_stream(user_input):
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

    async def run_stream(self, user_input: str) -> AsyncIterator[AgentEvent]:
        """Run the agent and stream intermediate events.

        Args:
            user_input: Natural language user query.

        Yields:
            AgentEvent values describing model output, tool calls, and final result.
        """
        self._state = AgentState.REASONING
        yield AgentEvent(kind="status", content="Analyzing request")

        system_prompt = f"""You are L.I.R.A., an AI assistant for personal finance management.

Your capabilities:
- list_accounts: List all accounts with their balances
- create_account: Create a new financial account
- create_transaction: Record income or expenses
- get_transactions: View recent transactions

Available tools:
{self._tools_schema}

Instructions:
1. Parse the user's natural language request
2. If the user wants to see data, call the appropriate tool(s)
3. Return results in a friendly format
4. If creating data, confirm with user first

IMPORTANT: When calling tools, respond ONLY with JSON like:
{{"tool_calls": [{{"name": "tool_name", "arguments": {{"arg1": "value1"}}}}]}}

If no tools needed, respond with plain text."""

        conversation = self._build_conversation(
            system_prompt=system_prompt, user_input=user_input
        )

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
            if tool_calls:
                self._state = AgentState.ACTING
                yield AgentEvent(kind="status", content="Executing tools")

                results: list[Any] = []
                resolved_calls: list[dict[str, Any]] = []
                for call in tool_calls:
                    tool_name = call["name"]
                    arguments = call["arguments"]
                    resolved_calls.append(call)

                    yield AgentEvent(
                        kind="tool_call",
                        payload={"name": tool_name, "arguments": arguments},
                    )

                    tool = self.tool_registry.get(tool_name)
                    if tool is None:
                        error_text = f"Unknown tool: {tool_name}"
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

                    result = await tool.execute(**arguments)
                    if result.success:
                        results.append(result.data)
                    else:
                        results.append(f"Error: {result.error}")

                    yield AgentEvent(
                        kind="tool_result",
                        payload={
                            "name": tool_name,
                            "success": result.success,
                            "error": result.error,
                            "data": result.data,
                        },
                    )

                final_message = self._format_results(results)
                self._state = AgentState.COMPLETE
                response = AgentResponse(
                    state=AgentState.COMPLETE,
                    message=final_message,
                    tool_calls=resolved_calls,
                    iterations=1,
                )
                self._append_history(
                    user_input=user_input, assistant_output=final_message
                )
                yield AgentEvent(
                    kind="final", content=final_message, payload={"response": response}
                )
                return

            self._state = AgentState.COMPLETE
            final_message = (
                response_text or "I didn't understand that. Can you rephrase?"
            )
            response = AgentResponse(
                state=AgentState.COMPLETE,
                message=final_message,
                iterations=1,
            )
            self._append_history(user_input=user_input, assistant_output=final_message)
            yield AgentEvent(
                kind="final", content=final_message, payload={"response": response}
            )

        except Exception as e:
            logger.exception("Agent error")
            self._state = AgentState.ERROR
            message = f"I encountered an error: {e!s}"
            response = AgentResponse(
                state=AgentState.ERROR,
                message=message,
                error=str(e),
            )
            self._append_history(user_input=user_input, assistant_output=message)
            yield AgentEvent(
                kind="error", content=message, payload={"response": response}
            )

    def _build_conversation(self, system_prompt: str, user_input: str) -> str:
        """Build conversation text with recent history included."""
        lines = [f"System: {system_prompt}", ""]

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

        try:
            data = json.loads(response_text)
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
