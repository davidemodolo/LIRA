"""Rich-based CLI console for L.I.R.A.

Provides an interactive terminal interface for financial management.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import typer
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from lira.version import __version__

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

console = Console(
    theme=Theme(
        {
            "info": "cyan",
            "warning": "yellow",
            "error": "red bold",
            "success": "green",
        }
    ),
    highlight=True,
)


@app.callback()
def main(
    interactive: bool = typer.Option(
        False, "--interactive", "-i", help="Start interactive mode"
    ),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug mode"),
) -> None:
    """L.I.R.A. CLI - AI-native personal finance tracker."""
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if interactive:
        run_interactive()
        raise typer.Exit()

    console.print(
        Panel.fit(
            "[bold cyan]L.I.R.A.[/bold cyan] v" + __version__ + "\n"
            "LIRA Is Recursive Accounting\n"
            "AI-native personal finance tracker",
            border_style="cyan",
        )
    )
    console.print("[dim]Use --interactive or -i to start chat mode[/dim]")
    console.print("[dim]Use --help for available commands[/dim]")


def run_interactive() -> None:
    """Run the interactive chat interface."""
    from lira.core.agent import Agent, AgentConfig
    from lira.db.session import init_database

    init_database()
    agent = Agent(
        config=AgentConfig(
            enable_self_correction=True,
        )
    )

    session_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(session_loop)

    console.print("[dim]Loading model for interactive session...[/dim]")
    warmup_ok = session_loop.run_until_complete(warmup_agent(agent))
    if warmup_ok:
        console.print("[dim]Model ready. Session memory enabled.[/dim]")
    else:
        console.print("[yellow]Model warmup skipped. Continuing anyway.[/yellow]")

    show_trace = False
    last_trace: list[str] = []

    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import InMemoryHistory

    prompt_session = PromptSession(history=InMemoryHistory())

    console.print("\n[green]Interactive mode started. Type 'exit' to quit.[/green]")
    console.print(
        "[dim]Commands: /trace toggle trace, /show-trace view last trace, /reset clear session[/dim]\n"
    )

    try:
        while True:
            try:
                user_input = prompt_session.prompt(
                    HTML("<b><ansiblue>You ></ansiblue></b> ")
                )
                command = user_input.strip().lower()

                if command in ("exit", "quit", "q"):
                    console.print("[yellow]Goodbye![/yellow]")
                    break

                if not user_input.strip():
                    continue

                if command in ("/trace", "/toggle-trace"):
                    show_trace = not show_trace
                    status = "enabled" if show_trace else "disabled"
                    console.print(f"[cyan]Trace display {status}.[/cyan]")
                    continue

                if command in ("/show-trace", "/show"):
                    display_trace(last_trace)
                    continue

                if command in ("/reset", "/new"):
                    agent.reset()
                    last_trace = []
                    console.print("[cyan]Conversation context cleared.[/cyan]")
                    continue

                start_time = time.time()
                trace_lines: list[str] = []
                draft_text = ""

                with Live(
                    _render_live_trace(
                        draft_text=draft_text, trace_lines=trace_lines, elapsed=0.0
                    ),
                    console=console,
                    refresh_per_second=12,
                    transient=True,
                ) as live:
                    draft_state = {"text": draft_text}

                    def on_event(
                        event: Any,
                        trace_ref: list[str] = trace_lines,
                        start_ref: float = start_time,
                        live_ref: Live = live,
                        state: dict[str, str] = draft_state,
                    ) -> None:
                        if event.kind == "status" and event.content:
                            trace_ref.append(f"state> {event.content}")
                        elif event.kind == "tool_call":
                            trace_ref.append(_format_tool_call(event.payload))
                        elif event.kind == "tool_result":
                            trace_ref.append(_format_tool_result(event.payload))
                            # Reset draft when new loop starts
                            state["text"] = ""
                        elif event.kind == "llm_token" and event.content:
                            state["text"] += event.content

                        live_ref.update(
                            _render_live_trace(
                                draft_text=state["text"],
                                trace_lines=trace_ref,
                                elapsed=time.time() - start_ref,
                            )
                        )

                    response = session_loop.run_until_complete(
                        process_query(agent, user_input, event_handler=on_event)
                    )

                elapsed = time.time() - start_time
                last_trace = response.get("trace", [])
                display_response(response, elapsed, show_trace=show_trace)

            except KeyboardInterrupt:
                console.print("\n[yellow]Interrupted. Goodbye![/yellow]")
                break
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                if logging.getLogger().level == logging.DEBUG:
                    logger.exception("Interactive error")
    finally:
        try:
            session_loop.run_until_complete(agent.llm_provider.close())
        finally:
            session_loop.close()
            asyncio.set_event_loop(None)


def _truncate_text(value: str, max_chars: int = 250) -> str:
    """Truncate long text for terminal display."""
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."


def _format_tool_call(payload: dict[str, Any]) -> str:
    """Format a tool call line for trace output."""
    name = str(payload.get("name", "unknown"))
    arguments = payload.get("arguments", {})
    rendered_args = _truncate_text(json.dumps(arguments, default=str), max_chars=180)
    return f"tool> {name}({rendered_args})"


def _format_tool_result(payload: dict[str, Any]) -> str:
    """Format a tool result line for trace output."""
    name = str(payload.get("name", "unknown"))
    success = bool(payload.get("success"))
    status = "ok" if success else "error"

    if success:
        preview = _truncate_text(
            json.dumps(payload.get("data"), default=str), max_chars=180
        )
    else:
        preview = _truncate_text(
            str(payload.get("error", "unknown error")), max_chars=180
        )

    return f"tool< {name} [{status}] {preview}"


def _render_live_trace(
    draft_text: str, trace_lines: list[str], elapsed: float
) -> Panel:
    """Build the live progress panel while the model is running."""
    trace_block = (
        "\n".join(trace_lines[-8:]) if trace_lines else "waiting for activity..."
    )

    body = Group(
        Text(f"Running... {elapsed:.1f}s", style="cyan"),
        Text("Thinking and tools", style="bold yellow"),
        Text(trace_block, style="yellow"),
        Text(""),
        Text("Model response (live)", style="bold green"),
        (
            Text(draft_text, style="green")
            if draft_text
            else Text("waiting for model output...", style="green")
        ),
    )
    return Panel(body, title="L.I.R.A. Live", border_style="cyan")


def display_trace(trace_lines: list[str]) -> None:
    """Display the most recent trace log."""
    if not trace_lines:
        console.print("[dim]No trace available yet.[/dim]")
        return

    console.print(
        Panel(
            "\n".join(trace_lines),
            title="Thinking and tools",
            border_style="yellow",
        )
    )


async def warmup_agent(agent: Any) -> bool:
    """Warm up the model once at session start."""
    try:
        await agent.llm_provider.acomplete(
            "Reply with exactly READY.",
            temperature=0,
        )
        return True
    except Exception:
        return False


async def process_query(
    agent: Any,
    query: str,
    event_handler: Callable[[Any], None] | None = None,
) -> dict[str, Any]:
    """Process a user query through the agent.

    Args:
        agent: Persistent agent instance for the interactive session
        query: Natural language query
        event_handler: Optional callback for streamed agent events

    Returns:
        Agent response
    """
    trace_lines: list[str] = []
    draft_chunks: list[str] = []
    final_response = None

    async for event in agent.run_stream(query):
        if event_handler:
            event_handler(event)

        if event.kind == "status" and event.content:
            trace_lines.append(f"state> {event.content}")
        elif event.kind == "tool_call":
            trace_lines.append(_format_tool_call(event.payload))
        elif event.kind == "tool_result":
            trace_lines.append(_format_tool_result(event.payload))
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
        }

    return {
        "message": final_response.message,
        "state": final_response.state,
        "iterations": final_response.iterations,
        "data": final_response.data,
        "error": final_response.error,
        "trace": trace_lines,
        "draft": "".join(draft_chunks),
    }


def display_response(
    response: dict[str, Any], elapsed: float = 0, show_trace: bool = False
) -> None:
    """Display agent response in Rich format.

    Args:
        response: Agent response dict
        elapsed: Time taken in seconds
        show_trace: Whether to show thinking/tool trace after final response
    """
    if response["error"]:
        console.print(f"[red]Error: {response['error']}[/red]")
        if show_trace:
            display_trace(response.get("trace", []))
        return

    console.print("\n[green bold]L.I.R.A.[/green bold]")

    if elapsed > 0:
        elapsed_str = f"[dim]({elapsed:.1f}s)[/dim]"
        console.print(f" {elapsed_str}")

    message = response["message"]
    if message:
        console.print(Markdown(message))
    else:
        console.print("[dim]No response[/dim]")

    if response.get("data"):
        console.print("\n[dim]Additional data:[/dim]")
        console.print(response["data"])

    visualizations = response.get("visualizations", [])
    if visualizations:
        console.print(
            f"\n[cyan]Generated {len(visualizations)} visualization(s)[/cyan]"
        )
        for i, img_base64 in enumerate(visualizations, 1):
            try:
                import base64
                import io

                from PIL import Image

                img_data = base64.b64decode(img_base64)
                img = Image.open(io.BytesIO(img_data))
                img_path = f"/tmp/lira_plot_{i}.png"
                img.save(img_path)
                console.print(f"[dim]Plot saved to: {img_path}[/dim]")
            except ImportError:
                console.print(
                    f"[dim]Visualization {i} available ({len(img_base64)} bytes)[/dim]"
                )
            except Exception as e:
                console.print(f"[dim]Could not save plot {i}: {e}[/dim]")

    if show_trace:
        display_trace(response.get("trace", []))
    elif response.get("trace"):
        console.print("[dim]Trace hidden. Use /show-trace or /trace to view it.[/dim]")


@app.command()
def status() -> None:
    """Show L.I.R.A. system status."""
    from lira.db.session import DatabaseSession, init_database

    try:
        init_database()

        with DatabaseSession() as session:
            from lira.db.models import Account, Holding, Transaction

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
    from lira.db.session import DatabaseSession, init_database

    init_database()

    with DatabaseSession() as session:
        from lira.db.models import Account

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
    update_prices: bool = typer.Option(
        False, "--update-prices", "-u", help="Update stock prices"
    ),
) -> None:
    """Manage investment portfolio."""
    from lira.db.session import DatabaseSession, init_database

    init_database()

    if update_prices:
        console.print("[cyan]Updating stock prices...[/cyan]")
        asyncio.run(update_all_prices())
        console.print("[green]Prices updated![/green]")

    with DatabaseSession() as session:
        from lira.db.models import Holding

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
                    console.print(
                        f"[green]Updated {holding.symbol}: ${result['price']}[/green]"
                    )
            except Exception as e:
                console.print(f"[red]Failed to update {holding.symbol}: {e}[/red]")


async def fetch_stock_price(symbol: str) -> dict[str, Any]:
    """Fetch current stock price.

    Args:
        symbol: Stock ticker symbol

    Returns:
        Price data
    """
    try:
        import yfinance as yf

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
    console.print(f"[cyan]L.I.R.A.[/cyan] v{__version__}")


if __name__ == "__main__":
    app()
