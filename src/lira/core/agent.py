"""ReAct Agent implementation for L.I.R.A.

The agent uses a Reason + Act loop to autonomously handle user requests,
with self-correction capabilities for SQL errors and edge cases.

HITL (Human-in-the-Loop) support: mutation tool calls are intercepted before
execution and a diff preview is emitted. The caller must confirm before
the agent will commit changes to the database.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from lira.core.config import settings
from lira.core.init import check_initialization_needed, get_category_tree, get_currency
from lira.core.llm import LLMProvider, get_llm_provider
from lira.db.session import init_database
from lira.mcp.server import mcp, register_components

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


# Tools that mutate the database and require HITL confirmation
MUTATION_TOOLS = {
    "create_transaction",
    "create_account",
    "create_payment_method",
    "update_payment_method_balance",
    "transfer_between_payment_methods",
    "record_gain_loss",
    "create_category",
    "update_transactions",
    "create_persistent_plot",
    "create_investment",
    "set_asset_price",
    "update_asset_prices",
}


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
    hitl_enabled: bool = True


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
    pending_tool_calls: list[dict[str, Any]] | None = None


@dataclass
class AgentEvent:
    """Incremental event emitted while the agent is running."""

    kind: str
    content: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


def _build_mutation_preview(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build before/after preview for mutation tool calls.

    Queries current DB state so the user can see what will change.

    Args:
        tool_calls: List of parsed tool call dicts with name and arguments.

    Returns:
        List of preview dicts with tool, description, before, after fields.
    """
    from sqlalchemy import select

    from lira.db.models import Category, PaymentMethod
    from lira.db.session import DatabaseSession

    previews = []

    with DatabaseSession() as session:
        for call in tool_calls:
            tool = call["name"]
            args = call.get("arguments", {})
            preview: dict[str, Any] = {
                "tool": tool,
                "arguments": args,
                "before": None,
                "after": None,
            }

            if tool == "create_transaction":
                cat_name = args.get("category_name") or args.get("category_id")
                sec_cat_name = args.get("secondary_category_name") or args.get(
                    "secondary_category_id"
                )
                pm_name = args.get("payment_method_name") or args.get(
                    "payment_method_id"
                )
                preview["description"] = (
                    f"Create {args.get('transaction_type', 'transaction')}"
                )
                preview["before"] = None
                preview["after"] = {
                    "type": args.get("transaction_type"),
                    "amount": args.get("amount"),
                    "description": args.get("description"),
                    "merchant": args.get("merchant"),
                    "category": cat_name,
                    "secondary_category": sec_cat_name,
                    "payment_method": pm_name,
                }

            elif tool == "create_account":
                preview["description"] = f"Create account '{args.get('name')}'"
                preview["before"] = None
                preview["after"] = {
                    "name": args.get("name"),
                    "type": args.get("account_type", "checking"),
                    "balance": args.get("balance", 0),
                }

            elif tool == "create_payment_method":
                preview["description"] = f"Create payment method '{args.get('name')}'"
                preview["before"] = None
                preview["after"] = {
                    "name": args.get("name"),
                    "balance": args.get("balance", 0),
                    "is_default": args.get("is_default", False),
                }

            elif tool == "update_payment_method_balance":
                pm_name = args.get("payment_method_name", "")
                pm = session.execute(
                    select(PaymentMethod).where(PaymentMethod.name == pm_name)
                ).scalar_one_or_none()
                preview["description"] = f"Update balance of '{pm_name}'"
                preview["before"] = {
                    "name": pm_name,
                    "balance": float(pm.balance) if pm else None,
                }
                preview["after"] = {"name": pm_name, "balance": args.get("new_balance")}

            elif tool == "transfer_between_payment_methods":
                from_name = args.get("from_method", "")
                to_name = args.get("to_method", "")
                amount = args.get("amount", 0)
                from_pm = session.execute(
                    select(PaymentMethod).where(PaymentMethod.name == from_name)
                ).scalar_one_or_none()
                to_pm = session.execute(
                    select(PaymentMethod).where(PaymentMethod.name == to_name)
                ).scalar_one_or_none()
                from_bal = float(from_pm.balance) if from_pm else None
                to_bal = float(to_pm.balance) if to_pm else None
                preview["description"] = (
                    f"Transfer {amount} from '{from_name}' to '{to_name}'"
                )
                preview["before"] = {
                    from_name: from_bal,
                    to_name: to_bal,
                }
                preview["after"] = {
                    from_name: (
                        round(from_bal - float(amount), 4)
                        if from_bal is not None
                        else None
                    ),
                    to_name: (
                        round(to_bal + float(amount), 4) if to_bal is not None else None
                    ),
                }

            elif tool == "record_gain_loss":
                pm_name = args.get("payment_method_name", "")
                amount = float(args.get("amount", 0))
                pm = session.execute(
                    select(PaymentMethod).where(PaymentMethod.name == pm_name)
                ).scalar_one_or_none()
                cur_bal = float(pm.balance) if pm else None
                action = "gain" if amount >= 0 else "loss"
                preview["description"] = (
                    f"Record {action} of {abs(amount)} for '{pm_name}'"
                )
                preview["before"] = {"name": pm_name, "balance": cur_bal}
                preview["after"] = {
                    "name": pm_name,
                    "balance": (
                        round(cur_bal + amount, 4) if cur_bal is not None else None
                    ),
                }

            elif tool == "create_category":
                parent_id = args.get("parent_id")
                parent_name = None
                if parent_id:
                    parent = session.execute(
                        select(Category).where(Category.id == parent_id)
                    ).scalar_one_or_none()
                    parent_name = parent.name if parent else str(parent_id)
                preview["description"] = f"Create category '{args.get('name')}'"
                preview["before"] = None
                preview["after"] = {
                    "name": args.get("name"),
                    "parent": parent_name,
                }

            elif tool == "update_transactions":
                preview["description"] = "Bulk update transactions"
                preview["before"] = {
                    "filters": {k: v for k, v in args.items() if k != "dry_run"}
                }
                preview["after"] = {
                    "category_id": args.get("category_id"),
                    "dry_run": args.get("dry_run", True),
                }

            elif tool == "create_persistent_plot":
                preview["description"] = f"Add persistent plot '{args.get('name')}'"
                preview["before"] = None
                preview["after"] = {
                    "name": args.get("name"),
                    "plot_type": args.get("plot_type", "bar"),
                    "title": args.get("title", ""),
                }

            else:
                preview["description"] = f"Execute {tool}"
                preview["before"] = None
                preview["after"] = args

            previews.append(preview)

    return previews


async def _execute_tool_calls(
    tool_calls: list[dict[str, Any]],
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Execute a list of tool calls and record in audit log.

    Returns:
        Tuple of (results list, audit entries list)
    """
    import json as _json

    from lira.db.models import AuditLog
    from lira.db.session import DatabaseSession

    results: list[Any] = []
    audit_entries: list[dict[str, Any]] = []

    for call in tool_calls:
        tool_name = call["name"]
        arguments = call.get("arguments", {})

        try:
            res = await mcp.call_tool(tool_name, arguments)

            tool_data = ""
            for content_item in res.content:
                if content_item.type == "text":
                    tool_data += content_item.text

            mcp_res = res.to_mcp_result() if hasattr(res, "to_mcp_result") else res
            success = not getattr(mcp_res, "isError", False)

            if not success:
                results.append(f"Error: {tool_data}")
            else:
                try:
                    parsed = _json.loads(tool_data)
                except _json.JSONDecodeError:
                    parsed = tool_data

                results.append(parsed)

                # Record in audit log
                if tool_name in MUTATION_TOOLS:
                    record_id = None
                    table_name = _tool_to_table(tool_name)
                    if isinstance(parsed, dict):
                        record_id = parsed.get("id")

                    with DatabaseSession() as session:
                        entry = AuditLog(
                            table_name=table_name,
                            record_id=record_id,
                            operation=_tool_to_operation(tool_name),
                            tool_name=tool_name,
                            before_state=None,
                            after_state=_json.dumps(parsed) if parsed else None,
                            description=f"{tool_name}({_json.dumps(arguments)[:200]})",
                        )
                        session.add(entry)
                        audit_entries.append(
                            {"tool": tool_name, "record_id": record_id}
                        )

        except Exception as e:
            error_text = f"Tool failure: {tool_name} - {e!s}"
            results.append(error_text)

    return results, audit_entries


def _tool_to_table(tool_name: str) -> str:
    mapping = {
        "create_transaction": "transactions",
        "create_account": "accounts",
        "create_payment_method": "payment_methods",
        "update_payment_method_balance": "payment_methods",
        "transfer_between_payment_methods": "payment_methods",
        "record_gain_loss": "payment_methods",
        "create_category": "categories",
        "update_transactions": "transactions",
        "create_persistent_plot": "dashboard_plots",
    }
    return mapping.get(tool_name, tool_name)


def _tool_to_operation(tool_name: str) -> str:
    if tool_name.startswith("create_"):
        return "create"
    if tool_name.startswith("update_") or tool_name in {
        "transfer_between_payment_methods",
        "record_gain_loss",
    }:
        return "update"
    return "create"


class Agent:
    """ReAct agent for autonomous financial management.

    The agent follows a Reason + Act loop:
    1. Think: Analyze the user's request
    2. Plan: Determine which tools to use
    3. Act: Execute tool calls (with HITL confirmation for mutations)
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
        register_components()

        if llm_provider:
            self.llm_provider = llm_provider
        else:
            self.llm_provider = get_llm_provider()

        self._state = AgentState.IDLE
        self._history: list[dict[str, Any]] = []
        self._tools_schema = self._build_tools_schema()
        self._tools_list: list[dict[str, Any]] = self._build_tools_list()
        self._init_status = check_initialization_needed()
        self._category_tree = get_category_tree()
        self._currency = get_currency()

    @property
    def initialization_needed(self) -> dict[str, bool]:
        """Check what needs to be initialized."""
        return {
            "currency": self._init_status["currency_needed"],
            "payment_methods": self._init_status["payment_methods_needed"],
            "categories": self._init_status["categories_needed"],
            "accounts": self._init_status["accounts_needed"],
        }

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

    def _build_context_strings(self) -> tuple[str, str]:
        """Return (init_context, category_info) strings for system prompts."""
        init_msgs: list[str] = []
        if self._init_status["accounts_needed"]:
            init_msgs.append("A default 'Personal' account will be created automatically")
        if self._init_status["currency_needed"]:
            init_msgs.append("Ask the user for their base currency (e.g., USD, EUR, GBP)")
        if self._init_status["payment_methods_needed"]:
            init_msgs.append(
                "Ask the user for their payment methods with their starting balances"
                " (e.g., 'Cash: 100, Revolut: 500, BBVA: 200')"
            )
        if self._init_status["categories_needed"]:
            init_msgs.append(
                "Ask the user for their category hierarchy. Prompt with: 'Please provide"
                " your expense categories. For each main category, list the subcategories."
                " Example: FOOD (restaurant, groceries), TRANSPORT (gas, bus), etc.'"
            )

        init_context = ""
        if init_msgs:
            init_context = (
                "\n[SETUP REQUIRED] The first time running, please:\n- "
                + "\n- ".join(init_msgs)
                + "\nUse set_currency, create_payment_method (with balance), and"
                " get_categories tools as needed.\n"
            )

        category_info = ""
        if self._category_tree:
            cat_lines = []
            for parent, data in self._category_tree.items():
                subs = [s["name"] for s in data.get("subcategories", [])]
                if subs:
                    cat_lines.append(f"  {parent}: {', '.join(subs)}")
                else:
                    cat_lines.append(f"  {parent}")
            category_info = "\n[AVAILABLE CATEGORIES]\n" + "\n".join(cat_lines) + "\n"

        return init_context, category_info

    def _build_tools_list(self) -> list[dict[str, Any]]:
        """Build raw tools list (JSON schemas) for FunctionGemma chat template."""
        schemas: list[dict[str, Any]] = []
        for tool in mcp._local_provider._components.values():
            if not hasattr(tool, "parameters"):
                continue
            raw_params = tool.parameters or {}
            properties = raw_params.get("properties", {}) if isinstance(raw_params, dict) else {}
            required = raw_params.get("required", []) if isinstance(raw_params, dict) else []

            clean_props: dict[str, Any] = {}
            for name, prop in properties.items():
                if not isinstance(prop, dict):
                    continue
                clean: dict[str, Any] = {}
                for key in ("type", "description", "enum", "default"):
                    if key in prop:
                        clean[key] = prop[key]
                if "anyOf" in prop:
                    for variant in prop["anyOf"]:
                        if isinstance(variant, dict) and variant.get("type") != "null":
                            clean["type"] = variant.get("type", "string")
                            break
                clean_props[name] = clean

            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": {"type": "object", "properties": clean_props, "required": required},
                },
            })
        return schemas

    async def run(
        self,
        user_input: str,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> AgentResponse:
        """Run the agent with user input and return the final response."""
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

    async def run_confirmed(
        self,
        pending_tool_calls: list[dict[str, Any]],
    ) -> AsyncIterator[AgentEvent]:
        """Execute previously confirmed pending tool calls.

        Used by the HITL flow when the user clicks "Confirm" in the UI or CLI.
        Skips the LLM and directly executes the tool calls, recording them in
        the audit log.

        Args:
            pending_tool_calls: Tool calls that were previewed and confirmed.

        Yields:
            AgentEvent values describing tool calls and final result.
        """
        self._state = AgentState.ACTING
        yield AgentEvent(kind="status", content="Executing confirmed changes")

        results, audit_entries = await _execute_tool_calls(pending_tool_calls)

        for call, result in zip(pending_tool_calls, results):
            tool_name = call["name"]
            success = not (isinstance(result, str) and result.startswith("Error:"))
            yield AgentEvent(
                kind="tool_result",
                payload={
                    "name": tool_name,
                    "success": success,
                    "error": result if not success else None,
                    "data": result if success else None,
                },
            )

        summary = self._format_results(results)
        self._state = AgentState.COMPLETE
        message = f"Done. Changes applied:\n{summary}"
        response = AgentResponse(
            state=AgentState.COMPLETE,
            message=message,
            iterations=1,
            tool_calls=pending_tool_calls,
        )
        yield AgentEvent(kind="final", content=message, payload={"response": response})

    async def run_stream(
        self,
        user_input: str,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run the agent and stream intermediate events.

        When HITL is enabled and the agent produces mutation tool calls, the
        agent emits a ``mutation_preview`` event and pauses — returning
        WAITING_INPUT.  The caller must either call ``run_confirmed`` with the
        pending tool calls or send a follow-up message to cancel.

        Args:
            user_input: Natural language user query.
            conversation_history: Optional external conversation history
                                  (for stateless server mode)

        Yields:
            AgentEvent values describing model output, tool calls, and final result.
        """
        self._state = AgentState.REASONING

        today = datetime.now(timezone.utc).date().isoformat()
        init_context, category_info = self._build_context_strings()

        system_prompt = f"""You are L.I.R.A., an AI assistant for personal finance management.

Current date: {today}
Base currency: {self._currency}
{init_context}{category_info}
Available tools:
{self._tools_schema}

Instructions:
1. Parse the user's natural language request
2. If the user wants to see data, call the appropriate tool(s)
3. If creating a transaction, FIRST use list_accounts to find the correct account_id for the given account name.
4. Transactions can have primary and secondary categories for better organization (e.g., primary=FOOD, secondary=groceries)
5. If the user wants a chart or visualization, use generate_plot
6. Return results in a friendly format
7. Tool argument names must match the schema exactly (e.g. use transaction_type, not type)
8. When adding expenses, use the category system. Categories are hierarchical like FOOD -> bar-restaurant, groceries

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
                logger.info(
                    f"LLM response (len={len(response_text)}): {response_text[:300]}..."
                )

                tool_calls = self._parse_tool_calls(response_text)
                logger.info(f"Parsed tool_calls: {tool_calls}")

                if not tool_calls:
                    logger.warning(
                        "No tool calls parsed from LLM response, ending with text response"
                    )
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

                # --- HITL: intercept mutation tool calls ---
                mutation_calls = [c for c in tool_calls if c["name"] in MUTATION_TOOLS]
                read_calls = [c for c in tool_calls if c["name"] not in MUTATION_TOOLS]

                # First execute any read-only calls normally
                if read_calls:
                    self._state = AgentState.ACTING
                    yield AgentEvent(kind="status", content="Reading data")

                    read_results: list[Any] = []
                    for call in read_calls:
                        tool_name = call["name"]
                        arguments = call["arguments"]
                        resolved_calls.append(call)

                        yield AgentEvent(
                            kind="tool_call",
                            payload={"name": tool_name, "arguments": arguments},
                        )

                        try:
                            res = await mcp.call_tool(tool_name, arguments)
                            tool_data = ""
                            for content_item in res.content:
                                if content_item.type == "text":
                                    tool_data += content_item.text

                            mcp_res = (
                                res.to_mcp_result()
                                if hasattr(res, "to_mcp_result")
                                else res
                            )
                            success = not getattr(mcp_res, "isError", False)
                            tool_error = tool_data if not success else None

                            if tool_error:
                                read_results.append(f"Error: {tool_error}")
                            else:
                                try:
                                    parsed_data = json.loads(tool_data)
                                except json.JSONDecodeError:
                                    parsed_data = tool_data

                                read_results.append(parsed_data)
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
                                    "data": parsed_data if success else None,
                                },
                            )
                        except Exception as e:
                            error_text = f"Tool failure: {tool_name} - {e!s}"
                            read_results.append(error_text)
                            yield AgentEvent(
                                kind="tool_result",
                                payload={
                                    "name": tool_name,
                                    "success": False,
                                    "error": error_text,
                                    "data": None,
                                },
                            )

                    tool_results_text = "Tool Results:\n" + self._format_results(
                        read_results
                    )
                    conversation += f"\n\nAssistant (Tool call): {json.dumps({'tool_calls': read_calls})}\n\nSystem: {tool_results_text}\n\nRespond with JSON tool call or plain text:"

                    if not mutation_calls:
                        # Loop to get next response from LLM
                        continue

                # If there are mutation calls and HITL is enabled, pause for confirmation
                if mutation_calls and self.config.hitl_enabled:
                    previews = _build_mutation_preview(mutation_calls)

                    self._state = AgentState.WAITING_INPUT
                    preview_message = self._format_preview_message(previews)

                    yield AgentEvent(
                        kind="mutation_preview",
                        content=preview_message,
                        payload={
                            "pending_calls": mutation_calls,
                            "previews": previews,
                        },
                    )

                    response = AgentResponse(
                        state=AgentState.WAITING_INPUT,
                        message=preview_message,
                        iterations=iterations,
                        visualizations=visualizations,
                        tool_calls=resolved_calls,
                        pending_tool_calls=mutation_calls,
                    )
                    self._append_history(
                        user_input=user_input, assistant_output=preview_message
                    )
                    yield AgentEvent(
                        kind="final",
                        content=preview_message,
                        payload={"response": response},
                    )
                    return

                # HITL disabled or no mutations: execute all tool calls directly
                self._state = AgentState.ACTING
                yield AgentEvent(kind="status", content="Executing tools")

                results: list[Any] = []
                for call in tool_calls:
                    if call in resolved_calls:
                        continue
                    tool_name = call["name"]
                    arguments = call["arguments"]
                    resolved_calls.append(call)

                    yield AgentEvent(
                        kind="tool_call",
                        payload={"name": tool_name, "arguments": arguments},
                    )

                    try:
                        res = await mcp.call_tool(tool_name, arguments)
                        tool_data = ""
                        for content_item in res.content:
                            if content_item.type == "text":
                                tool_data += content_item.text

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
                                "data": parsed_data if success else None,
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

    def _format_preview_message(self, previews: list[dict[str, Any]]) -> str:
        """Format mutation previews into a human-readable confirmation request."""
        lines = ["I want to make the following changes:"]
        for i, p in enumerate(previews, 1):
            lines.append(f"\n**{i}. {p['description']}**")
            if p.get("before") is not None:
                lines.append(f"  Before: {json.dumps(p['before'])}")
            if p.get("after") is not None:
                lines.append(f"  After:  {json.dumps(p['after'])}")
        lines.append("\nConfirm to apply these changes, or cancel to abort.")
        return "\n".join(lines)

    def _build_conversation(
        self,
        system_prompt: str,
        user_input: str,
        external_history: list[dict[str, Any]] | None = None,
    ) -> str:
        """Build conversation text with recent history included."""
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
        """Parse model output into normalized tool calls."""
        if "{" not in response_text:
            return []

        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}")
        if start_idx == -1 or end_idx == -1 or start_idx > end_idx:
            return []

        json_str = response_text[start_idx : end_idx + 1]

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON: {e}")
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


def get_agent(config: AgentConfig | None = None) -> Agent:
    """Return the appropriate agent for the configured LLM provider.

    When LLM_PROVIDER=local, returns a FunctionGemmaAgent that uses the
    chat template directly for tool calls. Otherwise returns the standard Agent.
    """
    from lira.core.config import settings

    if settings.llm_provider == "local":
        from lira.core.fg_agent import FunctionGemmaAgent

        return FunctionGemmaAgent(config=config)

    return Agent(config=config)
