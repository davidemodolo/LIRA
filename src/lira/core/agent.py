"""ReAct Agent implementation for L.I.R.A.

The agent uses a Reason + Act loop to autonomously handle user requests,
with self-correction capabilities for SQL errors and edge cases.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from lira.core.llm import OllamaProvider, get_ollama_provider
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


@dataclass
class AgentResponse:
    """Response from agent execution."""

    state: str
    message: str
    data: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    iterations: int = 0


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
        self.llm_provider = llm_provider or get_ollama_provider(
            base_url=self.config.ollama_base_url,
            model=self.config.model,
        )
        self._state = AgentState.IDLE
        self._history: list[dict[str, Any]] = []
        self._tools_schema = self._build_tools_schema()

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
            description = "List all accounts. Returns account details including balance."

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
                        "amount": {"type": "number", "description": "Transaction amount"},
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
                        "account_id": {"type": "integer", "description": "Account ID (optional)"},
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
                self, name: str, account_type: str = "checking", balance: float = 0.0, **kwargs: Any
            ) -> ToolResult:
                try:
                    with DatabaseSession() as session:
                        repo = AccountRepository(session)
                        a = repo.create(
                            name=name, account_type=account_type, balance=Decimal(str(balance))
                        )
                        return ToolResult(
                            success=True,
                            data={"id": a.id, "name": a.name, "balance": float(a.balance)},
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
                            "enum": ["checking", "savings", "credit_card", "investment"],
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
            schema = tool.get_schema()
            tools_desc.append(f"- {tool.name}: {tool.description}")

        return "\n".join(tools_desc)

    async def run(self, user_input: str) -> AgentResponse:
        """Run the agent with user input."""
        self._state = AgentState.REASONING
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

        conversation = f"""System: {system_prompt}

User: {user_input}

Respond with JSON tool call or plain text:"""

        try:
            response_text = await self.llm_provider.acomplete(
                conversation, temperature=self.config.temperature
            )

            response_text = self._clean_response(response_text)

            tool_result = self._parse_and_execute(response_text)

            if tool_result:
                return AgentResponse(
                    state=AgentState.COMPLETE,
                    message=tool_result,
                    iterations=1,
                )

            self._state = AgentState.COMPLETE

            return AgentResponse(
                state=AgentState.COMPLETE,
                message=response_text or "I didn't understand that. Can you rephrase?",
                iterations=1,
            )

        except Exception as e:
            logger.exception("Agent error")
            self._state = AgentState.ERROR
            return AgentResponse(
                state=AgentState.ERROR,
                message=f"I encountered an error: {e!s}",
                error=str(e),
            )

    def _parse_and_execute(self, response_text: str) -> str | None:
        """Parse JSON tool calls and execute them (sync wrapper)."""
        try:
            if "{" not in response_text:
                return None

            import json

            data = json.loads(response_text)

            if "tool_calls" in data:
                results = []
                for call in data["tool_calls"]:
                    tool_name = call.get("name")
                    arguments = call.get("arguments", {})

                    tool = self.tool_registry.get(tool_name)
                    if tool:
                        result = self._execute_tool_sync(tool, arguments)
                        if result.success:
                            results.append(result.data)
                        else:
                            results.append(f"Error: {result.error}")
                    else:
                        results.append(f"Unknown tool: {tool_name}")

                if results:
                    return self._format_results(results)
                return None

        except json.JSONDecodeError:
            pass

        return None

    def _execute_tool_sync(self, tool: Tool, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool synchronously."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, tool.execute(**arguments))
                return future.result()
        except RuntimeError:
            return asyncio.run(tool.execute(**arguments))

            import json

            data = json.loads(response_text)

            if "tool_calls" in data:
                results = []
                for call in data["tool_calls"]:
                    tool_name = call.get("name")
                    arguments = call.get("arguments", {})

                    tool = self.tool_registry.get(tool_name)
                    if tool:
                        import asyncio

                        result = asyncio.run(tool.execute(**arguments))
                        if result.success:
                            results.append(result.data)
                        else:
                            results.append(f"Error: {result.error}")
                    else:
                        results.append(f"Unknown tool: {tool_name}")

                if results:
                    return self._format_results(results)
                return None

        except json.JSONDecodeError:
            pass

        return None

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
        response = re.sub(r"\n?```$", "", response)

        return response

    def reset(self) -> None:
        """Reset agent state and history."""
        self._state = AgentState.IDLE
        self._history.clear()
