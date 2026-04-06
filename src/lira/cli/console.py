"""Textual-based TUI console for L.I.R.A.

Provides an interactive terminal interface with:
- Scrollable message history
- Collapsible thinking/tool trace panels
- Command autocomplete with hints
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Header, Input, RichLog, Static

from lira.version import __version__

if TYPE_CHECKING:
    from lira.core.agent import Agent

_REMOTE_API_URL: str | None = None  # set by --server CLI option or LIRA_API_URL env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = typer.Typer(
    name="lira",
    help="L.I.R.A. - AI-native personal finance tracker",
    add_completion=False,
    invoke_without_command=True,
)

COMMANDS: dict[str, str] = {
    "/trace": "Toggle trace display",
    "/toggle-trace": "Toggle trace display",
    "/show-trace": "Show last trace",
    "/show": "Show last trace",
    "/reset": "Clear session context",
    "/new": "Clear session context",
    "/help": "Show available commands",
    "/clear": "Clear message history",
    "/copy": "Copy last L.I.R.A. response to clipboard",
}

COMMAND_ALIASES: dict[str, str] = {
    "/t": "/trace",
    "/sh": "/show-trace",
    "/s": "/show",
    "/r": "/reset",
    "/n": "/new",
    "/h": "/help",
    "/c": "/clear",
    "/q": "exit",
    "/e": "exit",
    "/cp": "/copy",
}


class CollapsiblePanel(Static):
    def __init__(self, title: str, collapsed: bool = False) -> None:
        super().__init__(title)
        self.collapsed = collapsed
        self._title = title
        self._content = ""
        self._update_styles()

    def _update_styles(self) -> None:
        arrow = ">" if self.collapsed else "v"
        self.update(f"[{arrow}] {self._title}")

    def toggle(self) -> None:
        self.collapsed = not self.collapsed
        self._update_styles()

    def set_content(self, content: str) -> None:
        self._content = content
        if not self.collapsed:
            self.refresh()

    def render(self) -> str:
        if self.collapsed:
            arrow = ">"
            return f"[{arrow}] {self._title}"
        arrow = "v"
        return f"[{arrow}] {self._title}\n{self._content}"


class MessageHistory(RichLog):
    def __init__(self, **kwargs) -> None:
        super().__init__(
            markup=True,
            highlight=False,
            auto_scroll=True,
            **kwargs,
        )
        self._last_lira_message: str = ""

    def add_user_message(self, text: str) -> None:
        self.write(f"[bold cyan]You >[/bold cyan] {text}")

    def add_lira_message(self, text: str) -> None:
        self._last_lira_message = text
        self.write(f"[bold green]L.I.R.A. >[/bold green] {text}")

    def add_trace_line(self, text: str) -> None:
        self.write(f"[dim]{text}[/dim]")

    def add_system_message(self, text: str) -> None:
        self.write(f"[yellow]{text}[/yellow]")

    def add_error(self, text: str) -> None:
        self.write(f"[red bold]Error:[/red bold] {text}")


class LIRAApp(App):
    CSS = """
    Screen {
        background: $surface;
    }

    #main {
        height: 100%;
        layout: vertical;
    }

    #history {
        height: 1fr;
        border: solid $border;
        padding: 1;
    }

    #command-input {
        width: 100%;
        dock: bottom;
    }

    #suggestions {
        dock: bottom;
        height: auto;
        background: $panel;
        padding: 0 2;
        color: $text-muted;
    }
    """

    def __init__(self, api_url: str | None = None) -> None:
        super().__init__()
        self.api_url: str | None = api_url or _REMOTE_API_URL
        self.agent: Agent | None = None
        self.show_trace = False
        self.last_trace: list[str] = []
        self.trace_widget: Static | None = None
        self._suggestions: list[tuple[str, str]] = []
        self._warmup_task: asyncio.Task[None] | None = None
        self._agent_task: asyncio.Task[None] | None = None
        # HITL state
        self._awaiting_hitl_confirm: bool = False
        self._pending_hitl_calls: list[dict[str, Any]] = []
        self._pending_hitl_trace: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main"):
            yield MessageHistory(id="history")
            yield Input(placeholder="Type your message or /command...", id="command-input")
            yield Static("", id="suggestions")

    def on_mount(self) -> None:
        self.init_agent()
        self.run_agent_warmup()

    def init_agent(self) -> None:
        if self.api_url:
            # Remote mode: no local agent or DB needed
            return

        from lira.core.agent import Agent, AgentConfig
        from lira.db.session import init_database

        init_database()

        self.agent = Agent(
            config=AgentConfig(
                enable_self_correction=True,
            )
        )

    def run_agent_warmup(self) -> None:
        history = self.query_one("#history", MessageHistory)

        if self.api_url:
            history.add_system_message(
                f"[dim]Remote mode — connected to [cyan]{self.api_url}[/cyan][/dim]"
            )
            history.add_system_message("\n[green]Interactive mode started.[/green]")
            history.add_system_message(
                "[dim]Commands: /trace, /show-trace, /reset, /help, /clear[/dim]"
            )
            input_widget = self.query_one("#command-input", Input)
            input_widget.focus()
            return

        history.add_system_message("[dim]Loading model for interactive session...[/dim]")

        async def warmup() -> None:
            if self.agent is None:
                return
            try:
                await self.agent.llm_provider.acomplete(
                    "Reply with exactly READY.",
                    temperature=0,
                )
                history.add_system_message("[dim]Model ready. Session memory enabled.[/dim]")
            except Exception:
                history.add_system_message(
                    "[yellow]Model warmup skipped. Continuing anyway.[/yellow]"
                )

            history.add_system_message("\n[green]Interactive mode started.[/green]")
            history.add_system_message(
                "[dim]Commands: /trace, /show-trace, /reset, /help, /clear[/dim]"
            )

            if self.agent is not None:
                init = self.agent.initialization_needed
                if any(init.values()):
                    missing = []
                    if init.get("currency"):
                        missing.append("your base currency (e.g. EUR, USD)")
                    if init.get("payment_methods"):
                        missing.append(
                            "your payment methods with starting balances "
                            "(e.g. 'Cash: 100, Revolut: 500, BBVA: 1200')"
                        )
                    if init.get("categories"):
                        missing.append(
                            "your expense categories — or just say 'use defaults' "
                            "to load the built-in hierarchy"
                        )
                    lines = "\n  • ".join(missing)
                    history.add_lira_message(
                        f"Fresh database detected. To get started, tell me:\n  • {lines}"
                    )

            input_widget = self.query_one("#command-input", Input)
            input_widget.focus()

        import asyncio

        self._warmup_task = asyncio.create_task(warmup())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        user_input = event.value.strip()
        if not user_input:
            return

        history = self.query_one("#history", MessageHistory)
        history.add_user_message(user_input)

        if user_input.lower() in ("exit", "quit", "q"):
            history.add_system_message("[yellow]Goodbye![/yellow]")
            self.exit()
            return

        # HITL: intercept y/n confirmation input
        if self._awaiting_hitl_confirm:
            self._awaiting_hitl_confirm = False
            if user_input.lower() in ("y", "yes"):
                history.add_system_message("[green]Confirmed. Applying changes...[/green]")
                self._agent_task = asyncio.create_task(
                    self._execute_confirmed_mutations(history)
                )
            else:
                history.add_system_message("[yellow]Cancelled. No changes were made.[/yellow]")
                self._pending_hitl_calls = []
                self._pending_hitl_trace = []
            event.input.value = ""
            self._update_suggestions("")
            return

        self.handle_command(user_input, history)
        event.input.value = ""
        self._update_suggestions("")

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_suggestions(event.value)

    def _update_suggestions(self, value: str) -> None:
        suggestions_widget = self.query_one("#suggestions", Static)
        self._suggestions = []

        if not value.startswith("/"):
            suggestions_widget.update("")
            return

        matches = []
        value_lower = value.lower()

        for cmd, desc in COMMANDS.items():
            if cmd.startswith(value_lower):
                matches.append((cmd, desc))

        if value_lower in COMMAND_ALIASES:
            resolved = COMMAND_ALIASES[value_lower]
            matches.insert(0, (resolved, COMMANDS.get(resolved, "")))

        self._suggestions = matches[:3]

        if self._suggestions:
            lines = []
            for cmd, desc in self._suggestions:
                if cmd == value:
                    lines.append(f"[bold]{cmd}[/bold] - {desc}")
                else:
                    lines.append(f"[dim]{cmd}[/dim] - {desc}")
            suggestions_widget.update("\n".join(lines))
        else:
            suggestions_widget.update("")

    def handle_command(self, user_input: str, history: MessageHistory) -> None:
        raw_input = user_input.strip()
        command = raw_input.lower()

        if command in ("exit", "quit", "q"):
            history.add_system_message("[yellow]Goodbye![/yellow]")
            self.exit()
            return

        if command.startswith("/") and command not in COMMANDS:
            if command in COMMAND_ALIASES:
                resolved = COMMAND_ALIASES[command]
                history.add_system_message(f"[dim]Resolved alias: {raw_input} -> {resolved}[/dim]")
                user_input = resolved
                command = resolved.lower()
            else:
                matches = [cmd for cmd in COMMANDS if cmd.startswith(command)]
                if len(matches) == 1:
                    resolved = matches[0]
                    history.add_system_message(f"[dim]Completed: {raw_input} -> {resolved}[/dim]")
                    user_input = resolved
                    command = resolved.lower()

        if command in ("/trace", "/toggle-trace"):
            self.show_trace = not self.show_trace
            status = "enabled" if self.show_trace else "disabled"
            history.add_system_message(f"[cyan]Trace display {status}.[/cyan]")
            return

        if command in ("/show-trace", "/show"):
            self.display_trace(history)
            return

        if command in ("/reset", "/new"):
            if self.agent is not None:
                self.agent.reset()
            self.last_trace = []
            history.add_system_message("[cyan]Conversation context cleared.[/cyan]")
            return

        if command in ("/help",):
            self.display_help(history)
            return

        if command in ("/clear",):
            history.clear()
            history.add_system_message("[dim]History cleared.[/dim]")
            return

        if command in ("/copy",):
            text = history._last_lira_message
            if text:
                self.app.copy_to_clipboard(text)
                history.add_system_message("[dim]Copied to clipboard.[/dim]")
            else:
                history.add_system_message("[dim]Nothing to copy yet.[/dim]")
            return

        self.run_agent(user_input, history)

    def display_help(self, history: MessageHistory) -> None:
        history.add_system_message("[bold]Available commands:[/bold]")
        for cmd, desc in COMMANDS.items():
            history.add_system_message(f"  [cyan]{cmd}[/cyan] - {desc}")

    def display_trace(self, history: MessageHistory) -> None:
        if not self.last_trace:
            history.add_system_message("[dim]No trace available yet.[/dim]")
            return

        history.add_system_message("[bold yellow]=== Trace ===[/bold yellow]")
        for line in self.last_trace:
            history.add_trace_line(line)
        history.add_system_message("[bold yellow]============[/bold yellow]")

    def run_agent(self, user_input: str, history: MessageHistory) -> None:
        history.add_system_message("[dim]Running...[/dim]")
        import asyncio

        self._agent_task = asyncio.create_task(self.run_agent_async(user_input, history))

    async def run_agent_async(self, user_input: str, history: MessageHistory) -> None:
        try:
            trace_lines: list[str] = []

            def on_event(event: Any) -> None:
                if event.kind == "status" and event.content:
                    trace_lines.append(f"[yellow]state> {event.content}[/yellow]")
                    history.add_trace_line(f"state> {event.content}")
                elif event.kind == "tool_call":
                    line = self._format_tool_call(event.payload)
                    trace_lines.append(line)
                    history.add_trace_line(line)
                elif event.kind == "tool_result":
                    line = self._format_tool_result(event.payload)
                    trace_lines.append(line)
                    history.add_trace_line(line)
                elif event.kind == "mutation_preview":
                    trace_lines.append("[yellow]⚠ mutation_preview[/yellow]")
                elif event.kind == "llm_token" and event.content:
                    pass

            response = await self._process_query(user_input, on_event)

            self.last_trace = response.get("trace", [])

            if response["error"] and response.get("state") != "waiting_input":
                history.add_error(response["error"])
                if self.show_trace:
                    self.display_trace(history)
                return

            # HITL: If the agent is waiting for input on a mutation preview, show the diff
            pending = response.get("pending_tool_calls")
            if pending and response.get("state") == "waiting_input":
                history.add_lira_message(response["message"])
                await self._handle_hitl_confirmation(pending, history, trace_lines)
                return

            history.add_lira_message(response["message"])

            if self.show_trace:
                self.display_trace(history)
            elif self.last_trace:
                history.add_system_message(
                    f"[dim]Trace hidden. Use /show-trace or /trace to view it. ({len(self.last_trace)} events)[/dim]"
                )
        except Exception as e:
            history.add_error(f"Error: {e}")

    async def _handle_hitl_confirmation(
        self,
        pending_calls: list[dict[str, Any]],
        history: MessageHistory,
        trace_lines: list[str],
    ) -> None:
        """Show a Rich diff table for pending mutations and prompt for confirmation."""

        history.add_system_message("[bold yellow]─── Proposed Changes ─────────────────────────────────────────[/bold yellow]")

        for i, call in enumerate(pending_calls, 1):
            tool_name = call.get("name", "?")
            args = call.get("arguments", {})
            history.add_system_message(
                f"[{i}] [cyan]{tool_name}[/cyan]  args: [dim]{json.dumps(args)[:200]}[/dim]"
            )

        history.add_system_message("[bold yellow]──────────────────────────────────────────────────────────────[/bold yellow]")
        history.add_system_message("[bold]Confirm? [y/N][/bold] ")

        # We need to get user input from the same input widget
        self._pending_hitl_calls = pending_calls
        self._pending_hitl_trace = trace_lines
        self._awaiting_hitl_confirm = True

    def _format_tool_call(self, payload: dict[str, Any]) -> str:
        name = str(payload.get("name", "unknown"))
        arguments = payload.get("arguments", {})
        rendered_args = self._truncate_text(json.dumps(arguments, default=str), max_chars=180)
        return f"[cyan]tool> {name}({rendered_args})[/cyan]"

    def _format_tool_result(self, payload: dict[str, Any]) -> str:
        name = str(payload.get("name", "unknown"))
        success = bool(payload.get("success"))
        status = "[green]ok[/green]" if success else "[red]error[/red]"

        if success:
            preview = self._truncate_text(
                json.dumps(payload.get("data"), default=str), max_chars=180
            )
        else:
            preview = self._truncate_text(str(payload.get("error", "unknown error")), max_chars=180)

        return f"[cyan]tool< {name} [{status}] {preview}[/cyan]"

    def _truncate_text(self, value: str, max_chars: int = 250) -> str:
        if len(value) <= max_chars:
            return value
        return value[: max_chars - 3] + "..."

    async def _execute_confirmed_mutations(self, history: MessageHistory) -> None:
        """Execute HITL-confirmed pending tool calls."""
        if not self._pending_hitl_calls:
            history.add_system_message("[yellow]No pending changes to apply.[/yellow]")
            return

        calls = self._pending_hitl_calls
        self._pending_hitl_calls = []
        self._pending_hitl_trace = []

        # Remote mode: delegate execution to the server
        if self.api_url:
            try:
                import httpx

                url = self.api_url.rstrip("/") + "/api/chat/confirm"
                async with httpx.AsyncClient(timeout=120) as client:
                    resp = await client.post(
                        url,
                        json={"pending_tool_calls": calls, "stream": False},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    msg = data.get("message", {}).get("content", "")
                    if msg:
                        history.add_lira_message(msg)
            except Exception as e:
                history.add_error(f"Error executing confirmed changes: {e}")
            return

        if self.agent is None:
            history.add_system_message("[yellow]No pending changes to apply.[/yellow]")
            return

        try:
            async for event in self.agent.run_confirmed(calls):
                if event.kind == "tool_result":
                    line = self._format_tool_result(event.payload)
                    history.add_trace_line(line)
                elif event.kind == "final":
                    resp = event.payload.get("response")
                    if resp:
                        history.add_lira_message(resp.message)
                elif event.kind == "status" and event.content:
                    history.add_trace_line(f"state> {event.content}")
        except Exception as e:
            history.add_error(f"Error executing confirmed changes: {e}")

    async def _process_query(
        self,
        query: str,
        event_handler: Any = None,
    ) -> dict[str, Any]:
        # ── Remote mode: stream from the server API ──────────────────────────
        if self.api_url:
            return await self._process_query_remote(query, event_handler)

        # ── Local mode ────────────────────────────────────────────────────────
        if self.agent is None:
            return {
                "message": "Agent not initialized.",
                "state": "error",
                "iterations": 0,
                "data": None,
                "error": "agent not initialized",
                "trace": [],
                "draft": "",
                "pending_tool_calls": None,
            }

        trace_lines: list[str] = []
        draft_chunks: list[str] = []
        final_response = None

        async for event in self.agent.run_stream(query):
            if event_handler:
                event_handler(event)

            if event.kind == "status" and event.content:
                trace_lines.append(f"state> {event.content}")
            elif event.kind == "tool_call":
                trace_lines.append(self._format_tool_call(event.payload))
            elif event.kind == "tool_result":
                trace_lines.append(self._format_tool_result(event.payload))
            elif event.kind == "llm_token" and event.content:
                draft_chunks.append(event.content)
            elif event.kind in {"final", "error"}:
                final_response = event.payload.get("response")

        if final_response is None:
            return {
                "message": "I encountered an unexpected runtime state.",
                "state": "error",
                "iterations": 0,
                "data": None,
                "error": "missing final response",
                "trace": trace_lines,
                "draft": "".join(draft_chunks),
                "pending_tool_calls": None,
            }

        return {
            "message": final_response.message,
            "state": final_response.state,
            "iterations": final_response.iterations,
            "data": final_response.data,
            "error": final_response.error,
            "trace": trace_lines,
            "draft": "".join(draft_chunks),
            "pending_tool_calls": final_response.pending_tool_calls,
        }

    async def _process_query_remote(
        self,
        query: str,
        event_handler: Any = None,
    ) -> dict[str, Any]:
        """Send query to the remote L.I.R.A. API and stream back events."""
        import httpx

        base_url = self.api_url.rstrip("/")  # type: ignore[union-attr]
        url = base_url + "/api/chat"

        # Build chat history for the server
        history_msgs = [
            {"role": "user", "content": query}
        ]

        trace_lines: list[str] = []
        draft_chunks: list[str] = []
        pending_tool_calls: list[dict[str, Any]] | None = None
        final_message = ""
        final_state = "complete"

        try:
            async with httpx.AsyncClient(timeout=300) as client, client.stream(
                "POST",
                url,
                json={"messages": history_msgs, "stream": True},
                headers={"Content-Type": "application/json"},
            ) as response:
                response.raise_for_status()
                line_buffer = ""
                async for chunk in response.aiter_text():
                    line_buffer += chunk
                    lines = line_buffer.split("\n")
                    line_buffer = lines.pop()
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            ev = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        kind = ev.get("kind", "")
                        content = ev.get("content", "")
                        payload = ev.get("payload", {}) or {}

                        # Build a minimal event-like object for the handler
                        class _Ev:
                            pass

                        fake_ev = _Ev()
                        fake_ev.kind = kind  # type: ignore[attr-defined]
                        fake_ev.content = content  # type: ignore[attr-defined]
                        fake_ev.payload = payload  # type: ignore[attr-defined]

                        if event_handler:
                            event_handler(fake_ev)

                        if kind == "llm_token" and content:
                            draft_chunks.append(content)
                        elif kind == "tool_call":
                            trace_lines.append(self._format_tool_call(payload))
                        elif kind == "tool_result":
                            trace_lines.append(self._format_tool_result(payload))
                        elif kind == "status" and content:
                            trace_lines.append(f"state> {content}")
                        elif kind == "final":
                            resp = payload.get("response") or {}
                            final_message = resp.get("message", "".join(draft_chunks))
                            final_state = resp.get("state", "complete")
                            pending_tool_calls = resp.get("pending_tool_calls")
                        elif kind == "mutation_preview":
                            pending_tool_calls = (payload or {}).get("pending_calls")
                            final_state = "waiting_input"

        except Exception as e:
            return {
                "message": "",
                "state": "error",
                "iterations": 0,
                "data": None,
                "error": str(e),
                "trace": trace_lines,
                "draft": "".join(draft_chunks),
                "pending_tool_calls": None,
            }

        if not final_message:
            final_message = "".join(draft_chunks)

        return {
            "message": final_message,
            "state": final_state,
            "iterations": 0,
            "data": None,
            "error": None,
            "trace": trace_lines,
            "draft": "".join(draft_chunks),
            "pending_tool_calls": pending_tool_calls,
        }


def run_interactive(api_url: str | None = None) -> None:
    app_instance = LIRAApp(api_url=api_url)
    app_instance.run()


@app.callback()
def main(
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Start interactive mode"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug mode"),
    server: str | None = typer.Option(
        None,
        "--server",
        "-s",
        help=(
            "L.I.R.A. server URL (e.g. http://homeserver:8000). "
            "Overrides LIRA_API_URL env var. "
            "When set, the CLI forwards all requests to the remote server."
        ),
    ),
) -> None:
    """L.I.R.A. CLI - AI-native personal finance tracker."""
    from rich.console import Console

    from lira.core.config import settings

    console = Console()

    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Resolve server URL: CLI flag > env var in config
    api_url = server or settings.api_url

    global _REMOTE_API_URL
    _REMOTE_API_URL = api_url

    if interactive:
        run_interactive(api_url=api_url)
        raise typer.Exit()

    console.print(
        Panel.fit(
            "[bold cyan]L.I.R.A.[/bold cyan] v" + __version__ + "\n"
            "LIRA Is Recursive Accounting\n"
            "AI-native personal finance tracker",
            border_style="cyan",
        )
    )
    if api_url:
        console.print(f"[dim]Remote mode: connected to [cyan]{api_url}[/cyan][/dim]")
    console.print("[dim]Use --interactive or -i to start chat mode[/dim]")
    console.print("[dim]Use --server URL to connect to a remote L.I.R.A. server[/dim]")
    console.print("[dim]Use --help for available commands[/dim]")


@app.command()
def status() -> None:
    """Show L.I.R.A. system status."""
    from lira.db.models import Account, Holding, Transaction
    from lira.db.session import DatabaseSession, init_database

    console = Console()

    try:
        init_database()

        with DatabaseSession() as session:
            account_count = session.query(Account).count()
            transaction_count = session.query(Transaction).count()
            holding_count = session.query(Holding).count()

        table = Table(title="System Status")
        table.add_column("Component", style="cyan")
        table.add_column("Count", style="green")

        table.add_row("Accounts", str(account_count))
        table.add_row("Transactions", str(transaction_count))
        table.add_row("Holdings", str(holding_count))

        console.print(table)

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@app.command()
def accounts(
    list_all: bool = typer.Option(True, "--list", "-l", help="List all accounts"),
) -> None:
    """Manage accounts."""
    from lira.db.models import Account
    from lira.db.session import DatabaseSession, init_database

    console = Console()
    init_database()

    with DatabaseSession() as session:
        accounts = session.query(Account).all()

        if not accounts:
            console.print("[yellow]No accounts found.[/yellow]")
            return

        table = Table(title="Accounts")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Type", style="yellow")
        table.add_column("Balance", style="magenta", justify="right")

        for account in accounts:
            table.add_row(
                str(account.id),
                account.name,
                account.account_type.value,
                f"{account.balance:.2f} {account.currency}",
            )

        console.print(table)


@app.command()
def portfolio(
    show: bool = typer.Option(True, "--show", "-s", help="Show portfolio"),
    update_prices: bool = typer.Option(False, "--update-prices", "-u", help="Update stock prices"),
) -> None:
    """Manage investment portfolio."""
    from lira.db.models import Holding
    from lira.db.session import DatabaseSession, init_database

    console = Console()
    init_database()

    if update_prices:
        console.print("[cyan]Updating stock prices...[/cyan]")
        asyncio.run(update_all_prices())
        console.print("[green]Prices updated![/green]")

    with DatabaseSession() as session:
        holdings = session.query(Holding).all()

        if not holdings:
            console.print("[yellow]No holdings found.[/yellow]")
            return

        table = Table(title="Portfolio Holdings")
        table.add_column("Symbol", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Quantity", style="yellow", justify="right")
        table.add_column("Avg Cost", style="magenta", justify="right")
        table.add_column("Current", style="blue", justify="right")
        table.add_column("Value", style="green", justify="right")
        table.add_column("Gain/Loss", style="red", justify="right")

        total_value = 0.0
        total_cost = 0.0

        for h in holdings:
            current = float(h.current_price or h.average_cost)
            value = float(h.quantity) * current
            cost = float(h.quantity) * float(h.average_cost)
            gain = value - cost
            gain_pct = (gain / cost * 100) if cost else 0

            total_value += value
            total_cost += cost

            gain_str = f"{gain:+.2f} ({gain_pct:+.1f}%)"
            gain_color = "green" if gain >= 0 else "red"

            table.add_row(
                h.symbol,
                h.name or h.symbol,
                f"{float(h.quantity):.4f}",
                f"${float(h.average_cost):.2f}",
                f"${current:.2f}",
                f"${value:.2f}",
                f"[{gain_color}]{gain_str}[/{gain_color}]",
            )

        console.print(table)

        total_gain = total_value - total_cost
        total_gain_pct = (total_gain / total_cost * 100) if total_cost else 0

        summary = Table(title="Portfolio Summary")
        summary.add_column("Metric", style="cyan")
        summary.add_column("Value", style="green", justify="right")

        summary.add_row("Total Value", f"${total_value:.2f}")
        summary.add_row("Total Cost", f"${total_cost:.2f}")
        summary.add_row(
            "Total Gain/Loss",
            f"[{'green' if total_gain >= 0 else 'red'}]{total_gain:+.2f} ({total_gain_pct:+.1f}%)[/]",
        )

        console.print(summary)


async def update_all_prices() -> None:
    """Update all stock prices from Yahoo Finance."""
    from lira.db.models import Holding
    from lira.db.session import DatabaseSession

    with DatabaseSession() as session:
        holdings = session.query(Holding).all()

        for holding in holdings:
            try:
                result = await fetch_stock_price(holding.symbol)
                if result["success"]:
                    holding.current_price = result["price"]
                    session.commit()
            except Exception:
                pass  # nosec B110


async def fetch_stock_price(symbol: str) -> dict[str, Any]:
    """Fetch current stock price."""
    import yfinance as yf

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        price = info.get("currentPrice", info.get("regularMarketPrice"))

        return {
            "success": True,
            "symbol": symbol.upper(),
            "price": price,
        }
    except Exception as e:
        return {
            "success": False,
            "symbol": symbol,
            "error": str(e),
        }


@app.command()
def version() -> None:
    """Show version information."""
    console = Console()
    console.print(f"[cyan]L.I.R.A.[/cyan] v{__version__}")


if __name__ == "__main__":
    app()
