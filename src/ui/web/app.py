"""
FastAPI web dashboard for paper trading.

Run standalone:
    uv run src/ui/web/app.py [--dir /path/to/bot] [--port 8080]

Serves a live dashboard at http://localhost:8080 and a JSON API at /api/data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from ui.paper_data import load_paper_data

# Resolved at import time; overridden by CLI --dir
_base_dir: str = "."

app = FastAPI(title="Paper Trading Dashboard")


@app.get("/", response_class=HTMLResponse)
async def dashboard_page() -> HTMLResponse:
    """Serve the HTML dashboard."""
    template_path = Path(__file__).resolve().parent / "templates" / "dashboard.html"
    html = template_path.read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/api/data")
async def api_data() -> dict:
    """Return paper trading data as JSON."""
    data = load_paper_data(_base_dir)
    return {
        "summary": data.summary,
        "trades": data.trades,
        "open_positions": data.open_positions,
        "closed_positions": data.closed_positions,
    }


def main() -> None:
    """Entry point for web dashboard."""
    global _base_dir  # noqa: PLW0603

    parser = argparse.ArgumentParser(description="Paper Trading Web Dashboard")
    parser.add_argument(
        "--dir",
        default=".",
        help="Base directory where paper_trades/ is located (default: .)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to serve on (default: 8080)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",  # noqa: S104
        help="Host to bind to (default: 0.0.0.0)",
    )
    args = parser.parse_args()
    _base_dir = args.dir

    print(f"Starting Paper Trading Web Dashboard on http://{args.host}:{args.port}")
    print(f"Reading from: {_base_dir}/paper_trades/")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    main()
