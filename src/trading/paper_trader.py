"""
Paper trading mode for simulated trading without real transactions.

Intercepts buy/sell operations and simulates them using real on-chain
price data, tracking virtual positions and P&L.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from solders.pubkey import Pubkey

from core.client import SolanaClient
from core.wallet import Wallet
from interfaces.core import AddressProvider, Platform, TokenInfo
from platforms import get_platform_implementations
from trading.base import Trader, TradeResult
from utils.logger import get_logger

logger = get_logger(__name__)

PAPER_TRADES_DIR = "paper_trades"


@dataclass
class PaperPosition:
    """A simulated token position."""

    mint: str
    symbol: str
    platform: str
    buy_price: float
    token_amount: float
    sol_spent: float
    buy_timestamp: str
    sell_price: float | None = None
    sol_received: float | None = None
    sell_timestamp: str | None = None
    pnl_sol: float | None = None
    pnl_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize position to dictionary."""
        return {
            "mint": self.mint,
            "symbol": self.symbol,
            "platform": self.platform,
            "buy_price": self.buy_price,
            "token_amount": self.token_amount,
            "sol_spent": self.sol_spent,
            "buy_timestamp": self.buy_timestamp,
            "sell_price": self.sell_price,
            "sol_received": self.sol_received,
            "sell_timestamp": self.sell_timestamp,
            "pnl_sol": self.pnl_sol,
            "pnl_pct": self.pnl_pct,
        }


@dataclass
class PaperWallet:
    """Simulated wallet tracking paper balance and positions."""

    initial_balance_sol: float = 1.0
    balance_sol: float = 1.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl_sol: float = 0.0
    positions: dict[str, PaperPosition] = field(default_factory=dict)
    closed_positions: list[PaperPosition] = field(default_factory=list)

    def record_buy(  # noqa: PLR0913
        self,
        mint: str,
        symbol: str,
        platform: str,
        price: float,
        token_amount: float,
        sol_spent: float,
    ) -> None:
        """Record a simulated buy."""
        self.balance_sol -= sol_spent
        self.positions[mint] = PaperPosition(
            mint=mint,
            symbol=symbol,
            platform=platform,
            buy_price=price,
            token_amount=token_amount,
            sol_spent=sol_spent,
            buy_timestamp=datetime.now(tz=UTC).isoformat(),
        )
        self.total_trades += 1

    def record_sell(
        self,
        mint: str,
        price: float,
        sol_received: float,
    ) -> PaperPosition | None:
        """Record a simulated sell and return closed position."""
        position = self.positions.pop(mint, None)
        if position is None:
            return None

        position.sell_price = price
        position.sol_received = sol_received
        position.sell_timestamp = datetime.now(tz=UTC).isoformat()
        position.pnl_sol = sol_received - position.sol_spent
        position.pnl_pct = (
            (position.pnl_sol / position.sol_spent) * 100
            if position.sol_spent > 0
            else 0.0
        )

        self.balance_sol += sol_received

        if position.pnl_sol >= 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
        self.total_pnl_sol += position.pnl_sol

        self.closed_positions.append(position)
        return position

    def get_summary(self) -> dict[str, Any]:
        """Get wallet performance summary."""
        return {
            "initial_balance_sol": self.initial_balance_sol,
            "current_balance_sol": round(self.balance_sol, 6),
            "total_pnl_sol": round(self.total_pnl_sol, 6),
            "total_pnl_pct": round(
                (self.total_pnl_sol / self.initial_balance_sol) * 100, 2
            )
            if self.initial_balance_sol > 0
            else 0.0,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate_pct": round((self.winning_trades / self.total_trades) * 100, 1)
            if self.total_trades > 0
            else 0.0,
            "open_positions": len(self.positions),
        }


class PaperBuyer(Trader):
    """Simulated buyer that uses real price data without sending transactions."""

    def __init__(  # noqa: PLR0913
        self,
        client: SolanaClient,
        wallet: Wallet,
        amount: float,
        slippage: float,
        paper_wallet: PaperWallet,
        *,
        extreme_fast_mode: bool = False,
        extreme_fast_token_amount: int = 0,
    ) -> None:
        """Initialize paper buyer.

        Args:
            client: Solana RPC client for price queries
            wallet: Real wallet (used only for address derivation)
            amount: SOL amount per trade
            slippage: Slippage tolerance
            paper_wallet: Simulated wallet for tracking
            extreme_fast_mode: Skip price validation
            extreme_fast_token_amount: Token amount for extreme fast mode
        """
        self.client = client
        self.wallet = wallet
        self.amount = amount
        self.slippage = slippage
        self.paper_wallet = paper_wallet
        self.extreme_fast_mode = extreme_fast_mode
        self.extreme_fast_token_amount = extreme_fast_token_amount

    async def execute(self, token_info: TokenInfo) -> TradeResult:
        """Simulate a buy using real on-chain price data."""
        try:
            implementations = get_platform_implementations(
                token_info.platform, self.client
            )
            address_provider = implementations.address_provider
            curve_manager = implementations.curve_manager

            if self.extreme_fast_mode:
                token_amount = float(self.extreme_fast_token_amount)
                token_price_sol = self.amount / token_amount if token_amount > 0 else 0
            else:
                pool_address = self._get_pool_address(token_info, address_provider)
                pool_state = await curve_manager.get_pool_state(pool_address)
                token_price_sol = pool_state.get("price_per_token")

                if token_price_sol is None or token_price_sol <= 0:
                    return TradeResult(
                        success=False,
                        platform=token_info.platform,
                        error_message=f"Invalid price: {token_price_sol}",
                    )
                token_amount = self.amount / token_price_sol

            sol_spent = self.amount
            mint_str = str(token_info.mint)

            if self.paper_wallet.balance_sol < sol_spent:
                return TradeResult(
                    success=False,
                    platform=token_info.platform,
                    error_message=(
                        f"Insufficient paper balance: "
                        f"{self.paper_wallet.balance_sol:.6f} SOL < {sol_spent:.6f} SOL"
                    ),
                )

            self.paper_wallet.record_buy(
                mint=mint_str,
                symbol=token_info.symbol,
                platform=token_info.platform.value,
                price=token_price_sol,
                token_amount=token_amount,
                sol_spent=sol_spent,
            )

            logger.info(
                "[PAPER] Bought %.6f %s at %.8f SOL/token (spent %.6f SOL)",
                token_amount,
                token_info.symbol,
                token_price_sol,
                sol_spent,
            )
            logger.info(
                "[PAPER] Balance: %.6f SOL",
                self.paper_wallet.balance_sol,
            )

            _save_paper_trade(
                "buy", token_info, token_price_sol, token_amount, sol_spent
            )

            return TradeResult(
                success=True,
                platform=token_info.platform,
                tx_signature=f"paper-buy-{mint_str[:8]}",
                amount=token_amount,
                price=token_price_sol,
            )

        except Exception as e:
            logger.exception("[PAPER] Buy simulation failed")
            return TradeResult(
                success=False,
                platform=token_info.platform,
                error_message=str(e),
            )

    def _get_pool_address(
        self, token_info: TokenInfo, address_provider: AddressProvider
    ) -> Pubkey:
        """Get pool address for price lookup."""
        if token_info.platform == Platform.PUMP_FUN:
            if token_info.bonding_curve:
                return token_info.bonding_curve
        elif token_info.platform == Platform.LETS_BONK:
            if token_info.pool_state:
                return token_info.pool_state
        return address_provider.derive_pool_address(token_info.mint)


class PaperSeller(Trader):
    """Simulated seller that uses real price data without sending transactions."""

    def __init__(
        self,
        client: SolanaClient,
        wallet: Wallet,
        slippage: float,
        paper_wallet: PaperWallet,
    ) -> None:
        """Initialize paper seller.

        Args:
            client: Solana RPC client for price queries
            wallet: Real wallet (used only for address derivation)
            slippage: Slippage tolerance
            paper_wallet: Simulated wallet for tracking
        """
        self.client = client
        self.wallet = wallet
        self.slippage = slippage
        self.paper_wallet = paper_wallet

    async def execute(
        self,
        token_info: TokenInfo,
        token_amount: float | None = None,
        token_price: float | None = None,
    ) -> TradeResult:
        """Simulate a sell using real on-chain price data.

        Args:
            token_info: Token information
            token_amount: Token amount to sell (from buy result)
            token_price: Current token price in SOL

        Returns:
            Simulated TradeResult
        """
        try:
            if token_amount is None or token_price is None or token_price <= 0:
                return TradeResult(
                    success=False,
                    platform=token_info.platform,
                    error_message="token_amount and token_price required for paper sell",
                )

            implementations = get_platform_implementations(
                token_info.platform, self.client
            )
            address_provider = implementations.address_provider
            curve_manager = implementations.curve_manager

            # Fetch current price for more realistic simulation
            try:
                pool_address = self._get_pool_address(token_info, address_provider)
                pool_state = await curve_manager.get_pool_state(pool_address)
                current_price = pool_state.get("price_per_token", token_price)
                if current_price and current_price > 0:
                    token_price = current_price
            except Exception:  # noqa: BLE001
                logger.debug(
                    "[PAPER] Could not fetch live price for sell, using buy price"
                )

            sol_received = token_amount * token_price
            mint_str = str(token_info.mint)

            position = self.paper_wallet.record_sell(
                mint=mint_str,
                price=token_price,
                sol_received=sol_received,
            )

            if position:
                logger.info(
                    "[PAPER] Sold %.6f %s at %.8f SOL/token (received %.6f SOL)",
                    token_amount,
                    token_info.symbol,
                    token_price,
                    sol_received,
                )
                logger.info(
                    "[PAPER] PnL: %+.6f SOL (%+.2f%%)",
                    position.pnl_sol,
                    position.pnl_pct,
                )
            else:
                logger.warning(
                    "[PAPER] No open position found for %s", token_info.symbol
                )

            summary = self.paper_wallet.get_summary()
            logger.info(
                "[PAPER] Balance: %.6f SOL | Total PnL: %+.6f SOL | Win rate: %.1f%%",
                summary["current_balance_sol"],
                summary["total_pnl_sol"],
                summary["win_rate_pct"],
            )

            _save_paper_trade(
                "sell", token_info, token_price, token_amount, sol_received
            )
            _save_paper_summary(self.paper_wallet)

            return TradeResult(
                success=True,
                platform=token_info.platform,
                tx_signature=f"paper-sell-{mint_str[:8]}",
                amount=token_amount,
                price=token_price,
            )

        except Exception as e:
            logger.exception("[PAPER] Sell simulation failed")
            return TradeResult(
                success=False,
                platform=token_info.platform,
                error_message=str(e),
            )

    def _get_pool_address(
        self, token_info: TokenInfo, address_provider: AddressProvider
    ) -> Pubkey:
        """Get pool address for price lookup."""
        if token_info.platform == Platform.PUMP_FUN:
            if token_info.bonding_curve:
                return token_info.bonding_curve
        elif token_info.platform == Platform.LETS_BONK:
            if token_info.pool_state:
                return token_info.pool_state
        return address_provider.derive_pool_address(token_info.mint)


def _save_paper_trade(
    action: str,
    token_info: TokenInfo,
    price: float,
    amount: float,
    sol_value: float,
) -> None:
    """Append a paper trade entry to the log file."""
    try:
        trades_dir = Path(PAPER_TRADES_DIR)
        trades_dir.mkdir(exist_ok=True)

        entry = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "action": action,
            "platform": token_info.platform.value,
            "mint": str(token_info.mint),
            "symbol": token_info.symbol,
            "price_sol": price,
            "token_amount": amount,
            "sol_value": sol_value,
        }

        log_path = trades_dir / "paper_trades.log"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        logger.exception("Failed to save paper trade")


def _save_paper_summary(paper_wallet: PaperWallet) -> None:
    """Persist the latest wallet summary to disk."""
    try:
        trades_dir = Path(PAPER_TRADES_DIR)
        trades_dir.mkdir(exist_ok=True)

        summary = paper_wallet.get_summary()
        summary["closed_positions"] = [
            p.to_dict() for p in paper_wallet.closed_positions
        ]

        summary_path = trades_dir / "paper_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2))
    except OSError:
        logger.exception("Failed to save paper summary")
