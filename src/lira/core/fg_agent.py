"""FunctionGemma agent for L.I.R.A.

Loaded automatically when LLM_PROVIDER=local. Uses the locally-finetuned
FunctionGemma model with its HuggingFace chat template, matching the training
format exactly: developer role in system position, tools passed to the template,
multi-turn via assistant/tool message roles.

Ollama and Groq providers use the standard Agent in agent.py unchanged.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from lira.core.agent import (
    MUTATION_TOOLS,
    Agent,
    AgentConfig,
    AgentEvent,
    AgentResponse,
    AgentState,
    _build_mutation_preview,
    _execute_tool_calls,
)
from lira.core.llm import LocalHFProvider

logger = logging.getLogger(__name__)


def _parse_fg_arguments(args_str: str) -> dict[str, Any]:
    """Parse FunctionGemma's key:value argument format into a Python dict.

    The template encodes strings as <escape>value<escape> and produces flat
    key:value pairs separated by commas.  We handle strings, numbers, and
    booleans.  Nested objects/arrays are left as raw strings (rare for LIRA tools).
    """
    result: dict[str, Any] = {}
    if not args_str:
        return result

    # Replace <escape>...<escape> quoted strings first — capture them
    # so commas/colons inside don't confuse the splitter.
    placeholder_map: dict[str, str] = {}

    def _capture(m: re.Match[str]) -> str:
        token = f"__STR{len(placeholder_map)}__"
        placeholder_map[token] = m.group(1)
        return token

    normalised = re.sub(r"<escape>(.*?)<escape>", _capture, args_str, flags=re.DOTALL)

    # Split on top-level commas (not inside nested {})
    depth = 0
    current: list[str] = []
    pairs: list[str] = []
    for ch in normalised:
        if ch == "{":
            depth += 1
            current.append(ch)
        elif ch == "}":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            pairs.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        pairs.append("".join(current).strip())

    for pair in pairs:
        if ":" not in pair:
            continue
        key, _, raw_val = pair.partition(":")
        key = key.strip()
        raw_val = raw_val.strip()

        # Restore captured strings
        if raw_val in placeholder_map:
            result[key] = placeholder_map[raw_val]
            continue

        # Boolean
        if raw_val == "true":
            result[key] = True
            continue
        if raw_val == "false":
            result[key] = False
            continue

        # Number
        try:
            result[key] = int(raw_val)
            continue
        except ValueError:
            pass
        try:
            result[key] = float(raw_val)
            continue
        except ValueError:
            pass

        # Fallback: raw string (e.g. nested object left as-is)
        result[key] = raw_val

    return result


# Matches the SYSTEM_PROMPT used during finetuning in finetune/run.py
_SYSTEM_PROMPT = (
    "You are L.I.R.A. (LIRA Is Recursive Accounting), a personal finance assistant. "
    "You help users manage their finances by calling the available tools. "
    "When the user's request requires multiple pieces of information, call multiple "
    "tools in parallel. Always use the most specific tool available."
)


class FunctionGemmaAgent(Agent):
    """Agent using a locally-finetuned FunctionGemma model.

    Key differences from the standard Agent:
    - LLM calls use apply_chat_template with tools= (matching training format)
    - Conversation history is a message list, not a flat string
    - Tool call output is parsed from <tool_call>...</tool_call> tokens
    """

    def __init__(self, config: AgentConfig | None = None) -> None:
        from lira.core.config import settings

        if not settings.local_model_path:
            raise ValueError("LOCAL_MODEL_PATH must be set when LLM_PROVIDER=local")
        provider = LocalHFProvider(model_path=settings.local_model_path)
        super().__init__(config=config, llm_provider=provider)

    @property
    def _provider(self) -> LocalHFProvider:
        return self.llm_provider  # type: ignore[return-value]

    # ── Prompt building ────────────────────────────────────────────────────────

    def _build_system_prompt(self, today: str, init_context: str, category_info: str) -> str:
        # Keep close to the bare _SYSTEM_PROMPT used during training.
        # Extra context (accounts, categories) is omitted here because the model
        # never saw it during finetuning and treating it as input confuses inference.
        return _SYSTEM_PROMPT

    # ── Output parsing ─────────────────────────────────────────────────────────

    def _parse_fg_tool_calls(self, response_text: str) -> list[dict[str, Any]]:
        """Parse FunctionGemma <start_function_call>...</end_function_call> output.

        FunctionGemma's chat template produces:
            <start_function_call>call:tool_name{key:'val',...}<end_function_call>

        We extract the tool name and then parse the argument block via a simple
        key:value lexer that handles the template's <escape>-quoted strings.
        """
        parsed: list[dict[str, Any]] = []
        # Match the function call blocks from the template
        blocks = re.findall(
            r"<start_function_call>call:(\w+)\{(.*?)}<end_function_call>",
            response_text,
            re.DOTALL,
        )
        for name, args_str in blocks:
            arguments = _parse_fg_arguments(args_str.strip())
            parsed.append({"name": name, "arguments": arguments})
        return parsed

    # ── Tool result helpers ────────────────────────────────────────────────────

    def _append_tool_turn(
        self,
        messages: list[dict[str, Any]],
        calls: list[dict[str, Any]],
        results: list[Any],
    ) -> None:
        """Append assistant tool_calls + tool result messages for multi-turn context."""
        messages.append({
            "role": "assistant",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {"name": c["name"], "arguments": c["arguments"]},
                }
                for c in calls
            ],
        })
        for call, result in zip(calls, results):
            messages.append({
                "role": "tool",
                "name": call["name"],
                "content": json.dumps(result) if not isinstance(result, str) else result,
            })

    # ── Main loop ──────────────────────────────────────────────────────────────

    async def run_stream(  # type: ignore[override]
        self,
        user_input: str,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """FunctionGemma ReAct loop using structured messages and the chat template."""
        self._state = AgentState.REASONING

        today = datetime.now(timezone.utc).date().isoformat()
        init_context, category_info = self._build_context_strings()
        system_prompt = self._build_system_prompt(today, init_context, category_info)

        yield AgentEvent(kind="status", content="Analyzing request (FunctionGemma local model)")

        messages: list[dict[str, Any]] = [
            {"role": "developer", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]

        visualizations: list[str] = []
        iterations = 0
        resolved_calls: list[dict[str, Any]] = []

        while iterations < self.config.max_iterations:
            iterations += 1
            try:
                response_text = await self._provider.generate_structured(
                    messages, self._tools_list
                )
                logger.info("FG response (len=%d): %s...", len(response_text), response_text[:300])
                yield AgentEvent(kind="llm_token", content=response_text)

                tool_calls = self._parse_fg_tool_calls(response_text)
                logger.info("Parsed tool_calls: %s", tool_calls)

                if not tool_calls:
                    self._state = AgentState.COMPLETE
                    final_message = response_text or "I didn't understand that. Can you rephrase?"
                    response = AgentResponse(
                        state=AgentState.COMPLETE,
                        message=final_message,
                        iterations=iterations,
                        visualizations=visualizations,
                        tool_calls=resolved_calls,
                    )
                    self._append_history(user_input=user_input, assistant_output=final_message)
                    yield AgentEvent(
                        kind="final", content=final_message, payload={"response": response}
                    )
                    return

                mutation_calls = [c for c in tool_calls if c["name"] in MUTATION_TOOLS]
                read_calls = [c for c in tool_calls if c["name"] not in MUTATION_TOOLS]

                # Execute read-only calls first, append to message context
                if read_calls:
                    self._state = AgentState.ACTING
                    yield AgentEvent(kind="status", content="Reading data")

                    for call in read_calls:
                        yield AgentEvent(
                            kind="tool_call",
                            payload={"name": call["name"], "arguments": call["arguments"]},
                        )

                    read_results, _ = await _execute_tool_calls(read_calls)
                    resolved_calls.extend(read_calls)

                    for call, result in zip(read_calls, read_results):
                        success = not (isinstance(result, str) and result.startswith("Error:"))
                        if success and call["name"] == "generate_plot" and isinstance(result, dict):
                            img = result.get("image_base64")
                            if img:
                                visualizations.append(img)
                        yield AgentEvent(
                            kind="tool_result",
                            payload={
                                "name": call["name"],
                                "success": success,
                                "data": result if success else None,
                                "error": result if not success else None,
                            },
                        )

                    self._append_tool_turn(messages, read_calls, read_results)

                    if not mutation_calls:
                        continue

                # HITL: pause for mutation confirmation
                if mutation_calls and self.config.hitl_enabled:
                    previews = _build_mutation_preview(mutation_calls)
                    self._state = AgentState.WAITING_INPUT
                    preview_message = self._format_preview_message(previews)
                    yield AgentEvent(
                        kind="mutation_preview",
                        content=preview_message,
                        payload={"pending_calls": mutation_calls, "previews": previews},
                    )
                    response = AgentResponse(
                        state=AgentState.WAITING_INPUT,
                        message=preview_message,
                        iterations=iterations,
                        visualizations=visualizations,
                        tool_calls=resolved_calls,
                        pending_tool_calls=mutation_calls,
                    )
                    self._append_history(user_input=user_input, assistant_output=preview_message)
                    yield AgentEvent(
                        kind="final", content=preview_message, payload={"response": response}
                    )
                    return

                # HITL disabled or no mutations — execute directly
                self._state = AgentState.ACTING
                yield AgentEvent(kind="status", content="Executing tools")

                for call in mutation_calls:
                    yield AgentEvent(
                        kind="tool_call",
                        payload={"name": call["name"], "arguments": call["arguments"]},
                    )

                results, _ = await _execute_tool_calls(mutation_calls)
                resolved_calls.extend(mutation_calls)

                for call, result in zip(mutation_calls, results):
                    success = not (isinstance(result, str) and result.startswith("Error:"))
                    if success and call["name"] == "generate_plot" and isinstance(result, dict):
                        img = result.get("image_base64")
                        if img:
                            visualizations.append(img)
                    yield AgentEvent(
                        kind="tool_result",
                        payload={
                            "name": call["name"],
                            "success": success,
                            "data": result if success else None,
                            "error": result if not success else None,
                        },
                    )

                self._append_tool_turn(messages, mutation_calls, results)

            except Exception as e:
                logger.exception("FunctionGemma agent error")
                self._state = AgentState.ERROR
                message = f"I encountered an error: {e!s}"
                response = AgentResponse(
                    state=AgentState.ERROR,
                    message=message,
                    error=str(e),
                    visualizations=visualizations,
                )
                self._append_history(user_input=user_input, assistant_output=message)
                yield AgentEvent(kind="error", content=message, payload={"response": response})
                return

        # Max iterations reached
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
