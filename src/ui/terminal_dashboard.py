"""
Rich-based terminal dashboard for paper trading.

Run standalone:
    uv run src/ui/terminal_dashboard.py [--dir /path/to/bot]

Refreshes every 2 seconds, reading from paper_trades/ directory.
"""

from __future__ import annotations

import argparse
import sys
import time

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ui.paper_data import load_paper_data


def _build_summary_panel(summary: dict) -> Panel:
    """Build the wallet summary panel."""
    balance = summary.get("current_balance_sol", 0.0)
    initial = summary.get("initial_balance_sol", 0.0)
    pnl = summary.get("total_pnl_sol", 0.0)
    pnl_pct = summary.get("total_pnl_pct", 0.0)
    wins = summary.get("winning_trades", 0)
    losses = summary.get("losing_trades", 0)
    total = summary.get("total_trades", 0)
    win_rate = summary.get("win_rate_pct", 0.0)
    open_pos = summary.get("open_positions", 0)

    pnl_color = "green" if pnl >= 0 else "red"

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("key", style="bold cyan", min_width=20)
    table.add_column("value", min_width=20)

    table.add_row("Initial Balance", f"{initial:.6f} SOL")
    table.add_row("Current Balance", f"{balance:.6f} SOL")
    table.add_row(
        "Total PnL",
        Text(f"{pnl:+.6f} SOL ({pnl_pct:+.2f}%)", style=pnl_color),
    )
    table.add_row("Trades (W/L)", f"{total}  ({wins}W / {losses}L)")
    table.add_row("Win Rate", f"{win_rate:.1f}%")
    table.add_row("Open Positions", str(open_pos))

    return Panel(table, title="[bold white]Paper Wallet[/]", border_style="blue")


def _build_open_positions_table(positions: list[dict]) -> Panel:
    """Build the open positions table."""
    table = Table(expand=True)
    table.add_column("Symbol", style="cyan", min_width=8)
    table.add_column("Mint", style="dim", max_width=16)
    table.add_column("Platform", style="magenta")
    table.add_column("Price (SOL)", justify="right")
    table.add_column("Amount", justify="right")
    table.add_column("SOL Spent", justify="right", style="yellow")
    table.add_column("Time", style="dim")

    for pos in positions[-20:]:
        table.add_row(
            pos.get("symbol", "?"),
            _short_mint(pos.get("mint", "")),
            pos.get("platform", "?"),
            f"{pos.get('price_sol', 0):.8f}",
            f"{pos.get('token_amount', 0):.4f}",
            f"{pos.get('sol_value', 0):.6f}",
            _short_time(pos.get("timestamp", "")),
        )

    if not positions:
        table.add_row("--", "--", "--", "--", "--", "--", "--")

    return Panel(table, title="[bold white]Open Positions[/]", border_style="green")


def _build_closed_positions_table(positions: list[dict]) -> Panel:
    """Build the closed positions table (most recent first)."""
    table = Table(expand=True)
    table.add_column("Symbol", style="cyan", min_width=8)
    table.add_column("Mint", style="dim", max_width=16)
    table.add_column("Buy Price", justify="right")
    table.add_column("Sell Price", justify="right")
    table.add_column("PnL (SOL)", justify="right")
    table.add_column("PnL %", justify="right")
    table.add_column("Sold At", style="dim")

    for pos in reversed(positions[-20:]):
        pnl = pos.get("pnl_sol", 0.0)
        pnl_pct = pos.get("pnl_pct", 0.0)
        pnl_style = "green" if pnl >= 0 else "red"

        table.add_row(
            pos.get("symbol", "?"),
            _short_mint(pos.get("mint", "")),
            f"{pos.get('buy_price', 0):.8f}",
            f"{pos.get('sell_price', 0):.8f}",
            Text(f"{pnl:+.6f}", style=pnl_style),
            Text(f"{pnl_pct:+.2f}%", style=pnl_style),
            _short_time(pos.get("sell_timestamp", "")),
        )

    if not positions:
        table.add_row("--", "--", "--", "--", "--", "--", "--")

    return Panel(table, title="[bold white]Closed Positions[/]", border_style="red")


def _build_recent_trades_table(trades: list[dict]) -> Panel:
    """Build recent trades log table."""
    table = Table(expand=True)
    table.add_column("Time", style="dim", min_width=8)
    table.add_column("Action", min_width=4)
    table.add_column("Symbol", style="cyan")
    table.add_column("Price (SOL)", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("SOL Value", justify="right", style="yellow")

    for trade in reversed(trades[-15:]):
        action = trade.get("action", "?")
        action_style = "green bold" if action == "buy" else "red bold"

        table.add_row(
            _short_time(trade.get("timestamp", "")),
            Text(action.upper(), style=action_style),
            trade.get("symbol", "?"),
            f"{trade.get('price_sol', 0):.8f}",
            f"{trade.get('token_amount', 0):.4f}",
            f"{trade.get('sol_value', 0):.6f}",
        )

    if not trades:
        table.add_row("--", "--", "--", "--", "--", "--")

    return Panel(table, title="[bold white]Recent Trades[/]", border_style="yellow")


_MIN_MINT_DISPLAY_LEN = 12


def _short_mint(mint: str) -> str:
    """Abbreviate a mint address."""
    if len(mint) > _MIN_MINT_DISPLAY_LEN:
        return f"{mint[:6]}..{mint[-4:]}"
    return mint


def _short_time(timestamp: str) -> str:
    """Extract HH:MM:SS from ISO timestamp."""
    if "T" in timestamp:
        time_part = timestamp.split("T")[1]
        return time_part[:8]
    return timestamp[:8] if timestamp else "--"


def build_dashboard(base_dir: str = ".") -> Layout:
    """Build the full dashboard layout."""
    data = load_paper_data(base_dir)

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=1),
        Layout(name="top", size=12),
        Layout(name="middle"),
        Layout(name="bottom"),
    )

    layout["header"].update(
        Text(
            "  PAPER TRADING DASHBOARD  ",
            style="bold white on blue",
            justify="center",
        )
    )
    layout["top"].update(_build_summary_panel(data.summary))

    layout["middle"].split_row(
        Layout(_build_open_positions_table(data.open_positions), name="open"),
        Layout(_build_recent_trades_table(data.trades), name="trades"),
    )

    layout["bottom"].update(_build_closed_positions_table(data.closed_positions))

    return layout


def run_dashboard(base_dir: str = ".", refresh_rate: float = 2.0) -> None:
    """Run the live terminal dashboard.

    Args:
        base_dir: Base directory where paper_trades/ is located.
        refresh_rate: Seconds between refreshes.
    """
    console = Console()
    console.print("[bold blue]Paper Trading Dashboard[/] starting...\n")
    console.print(f"Reading from: {base_dir}/paper_trades/")
    console.print("Press [bold]Ctrl+C[/] to exit.\n")

    try:
        with Live(
            build_dashboard(base_dir),
            console=console,
            refresh_per_second=1,
            screen=True,
        ) as live:
            while True:
                time.sleep(refresh_rate)
                live.update(build_dashboard(base_dir))
    except KeyboardInterrupt:
        console.print("\n[bold]Dashboard stopped.[/]")


def main() -> None:
    """Entry point for terminal dashboard."""
    parser = argparse.ArgumentParser(description="Paper Trading Terminal Dashboard")
    parser.add_argument(
        "--dir",
        default=".",
        help="Base directory where paper_trades/ is located (default: .)",
    )
    parser.add_argument(
        "--refresh",
        type=float,
        default=2.0,
        help="Refresh interval in seconds (default: 2.0)",
    )
    args = parser.parse_args()
    run_dashboard(args.dir, args.refresh)


if __name__ == "__main__":
    # Allow running from src/ directory
    sys.path.insert(
        0, str(__import__("pathlib").Path(__file__).resolve().parent.parent)
    )
    main()
