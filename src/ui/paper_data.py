"""
Shared data reader for paper trading UI dashboards.

Reads paper_trades.log and paper_summary.json produced by the paper trader.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PAPER_TRADES_DIR = "paper_trades"


@dataclass
class PaperDashboardData:
    """Aggregated paper trading data for UI display."""

    summary: dict[str, Any] = field(default_factory=dict)
    trades: list[dict[str, Any]] = field(default_factory=list)
    open_positions: list[dict[str, Any]] = field(default_factory=list)
    closed_positions: list[dict[str, Any]] = field(default_factory=list)


def load_paper_data(base_dir: str = ".") -> PaperDashboardData:
    """Load all paper trading data from disk.

    Args:
        base_dir: Base directory where paper_trades/ is located.

    Returns:
        Aggregated dashboard data.
    """
    trades_dir = Path(base_dir) / PAPER_TRADES_DIR
    data = PaperDashboardData()

    data.summary, data.closed_positions = _load_summary(trades_dir)
    data.trades = _load_trades(trades_dir)
    data.open_positions = _derive_open_positions(data.trades)

    return data


def _load_summary(
    trades_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read summary JSON; return (summary, closed_positions)."""
    summary_path = trades_dir / "paper_summary.json"
    if not summary_path.exists():
        return {}, []
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        closed = summary.pop("closed_positions", [])
    except (json.JSONDecodeError, OSError):
        return {}, []
    else:
        return summary, closed


def _load_trades(trades_dir: Path) -> list[dict[str, Any]]:
    """Read the newline-delimited trade log."""
    log_path = trades_dir / "paper_trades.log"
    if not log_path.exists():
        return []
    trades: list[dict[str, Any]] = []
    try:
        for line in log_path.read_text(encoding="utf-8").strip().splitlines():
            if line.strip():
                try:
                    trades.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return trades


def _derive_open_positions(
    trades: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Derive currently open positions from the trade log."""
    bought: dict[str, dict[str, Any]] = {}
    for trade in trades:
        mint = trade.get("mint", "")
        if trade.get("action") == "buy":
            bought[mint] = trade
        elif trade.get("action") == "sell":
            bought.pop(mint, None)
    return list(bought.values())
