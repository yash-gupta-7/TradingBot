"""Order execution abstraction: paper (simulated) vs live (real Kite orders).

PaperEngine decides *when* to enter/exit purely from index price and
indicators (unchanged). An OrderManager only decides *how a decided trade
becomes a fill* — this is the only thing that differs between paper and
live trading.
"""
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Fill:
    status: str  # "filled" or "rejected"
    price: float | None
    order_id: str | None = None


class PaperOrderManager:
    """Simulates an instant fill at the current market quote. Never
    rejects a trade — a quote lookup failure just means the trade
    proceeds with a None option price (paper P&L is priced off the
    index, not the option premium, so this has no financial effect)."""

    def __init__(self, kite=None):
        self.kite = kite

    def _quote_price(self, option_symbol: str | None) -> float | None:
        if self.kite is None or option_symbol is None:
            return None
        try:
            quote = self.kite.quote([f"BFO:{option_symbol}"])
            return quote.get(f"BFO:{option_symbol}", {}).get("last_price")
        except Exception as e:
            logger.error(f"Failed to fetch quote for {option_symbol}: {e}")
            return None

    def submit_entry(self, option_symbol: str | None, quantity: int) -> Fill:
        return Fill(status="filled", price=self._quote_price(option_symbol), order_id=None)

    def submit_exit(self, option_symbol: str | None, quantity: int) -> Fill:
        return Fill(status="filled", price=self._quote_price(option_symbol), order_id=None)
