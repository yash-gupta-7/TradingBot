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


class LiveOrderManager:
    """Places real Kite orders and polls for a terminal fill status.

    A rejected/timed-out *entry* just means no trade happened. A
    rejected/timed-out *exit* is the dangerous case (a real open
    position the bot can no longer confirm is closed) — it retries the
    SELL a bounded number of times before giving up loudly.
    """

    POLL_INTERVALS = (1, 2, 3, 4, 5)  # seconds between polls, ~15s total
    EXIT_RETRY_ATTEMPTS = 3

    def __init__(self, kite):
        self.kite = kite

    def _place_and_wait(self, transaction_type: str, option_symbol: str, quantity: int) -> Fill:
        try:
            order_id = self.kite.place_order(
                variety="regular",
                exchange="BFO",
                tradingsymbol=option_symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                order_type="MARKET",
                product="MIS",
            )
        except Exception as e:
            logger.error(f"place_order failed for {option_symbol}: {e}")
            return Fill(status="rejected", price=None, order_id=None)

        for wait_s in self.POLL_INTERVALS:
            time.sleep(wait_s)
            try:
                history = self.kite.order_history(order_id)
            except Exception as e:
                logger.error(f"order_history failed for {order_id}: {e}")
                continue
            last = history[-1] if history else {}
            status = last.get("status")
            if status == "COMPLETE":
                return Fill(status="filled", price=last.get("average_price"), order_id=order_id)
            if status in ("REJECTED", "CANCELLED"):
                logger.error(f"Order {order_id} for {option_symbol} ended in {status}")
                return Fill(status="rejected", price=None, order_id=order_id)

        logger.error(f"Order {order_id} for {option_symbol} did not reach a terminal status in time")
        return Fill(status="rejected", price=None, order_id=order_id)

    def submit_entry(self, option_symbol: str | None, quantity: int) -> Fill:
        if option_symbol is None:
            logger.error("Cannot place a live entry order with no resolved option contract")
            return Fill(status="rejected", price=None, order_id=None)
        return self._place_and_wait("BUY", option_symbol, quantity)

    def submit_exit(self, option_symbol: str | None, quantity: int) -> Fill:
        if option_symbol is None:
            logger.critical("Cannot place a live exit order with no resolved option contract — position is untracked!")
            return Fill(status="rejected", price=None, order_id=None)
        for attempt in range(1, self.EXIT_RETRY_ATTEMPTS + 1):
            fill = self._place_and_wait("SELL", option_symbol, quantity)
            if fill.status == "filled":
                return fill
            logger.error(f"Exit attempt {attempt}/{self.EXIT_RETRY_ATTEMPTS} failed for {option_symbol}")
        logger.critical(
            f"EXIT FAILED after {self.EXIT_RETRY_ATTEMPTS} attempts for {option_symbol} qty={quantity} — "
            "a real position may still be open. Manual intervention required."
        )
        return Fill(status="rejected", price=None, order_id=None)
