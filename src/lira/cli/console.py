"""Rich-based CLI console for L.I.R.A.

Provides an interactive terminal interface for financial management.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.theme import Theme

from lira import __version__

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
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Start interactive mode"),
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
    console.print("\n[green]Interactive mode started. Type 'exit' to quit.[/green]\n")

    while True:
        try:
            user_input = Prompt.ask("\n[bold blue]You[/bold blue]")

            if user_input.lower() in ("exit", "quit", "q"):
                console.print("[yellow]Goodbye![/yellow]")
                break

            if not user_input.strip():
                continue

            response = asyncio.run(process_query(user_input))
            display_response(response)

        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted. Goodbye![/yellow]")
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            if logging.getLogger().level == logging.DEBUG:
                logger.exception("Interactive error")


async def process_query(query: str) -> dict[str, Any]:
    """Process a user query through the agent.

    Args:
        query: Natural language query

    Returns:
        Agent response
    """
    from lira.core.agent import Agent, AgentConfig
    from lira.db.session import init_database

    init_database()

    config = AgentConfig(
        model="gemma4:31b",
        enable_self_correction=True,
        temperature=0.7,
    )
    agent = Agent(config=config)

    response = await agent.run(query)

    return {
        "message": response.message,
        "state": response.state,
        "iterations": response.iterations,
        "data": response.data,
        "error": response.error,
    }


def display_response(response: dict[str, Any]) -> None:
    """Display agent response in Rich format.

    Args:
        response: Agent response dict
    """
    if response["error"]:
        console.print(f"[red]Error: {response['error']}[/red]")
        return

    console.print("\n[green bold]L.I.R.A.[/green bold]")

    message = response["message"]
    if message:
        console.print(Markdown(message))
    else:
        console.print("[dim]No response[/dim]")

    if response.get("data"):
        console.print("\n[dim]Additional data:[/dim]")
        console.print(response["data"])


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
    update_prices: bool = typer.Option(False, "--update-prices", "-u", help="Update stock prices"),
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
                    console.print(f"[green]Updated {holding.symbol}: ${result['price']}[/green]")
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
