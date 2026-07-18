from execution.order_manager import Fill, PaperOrderManager


class _FakeKite:
    def __init__(self, price):
        self.price = price

    def quote(self, symbols):
        return {symbols[0]: {"last_price": self.price}}


def test_paper_entry_fills_at_quote_price():
    om = PaperOrderManager(kite=_FakeKite(123.45))
    fill = om.submit_entry("SENSEX2572575000CE", 20)
    assert fill == Fill(status="filled", price=123.45, order_id=None)


def test_paper_exit_fills_at_quote_price():
    om = PaperOrderManager(kite=_FakeKite(98.7))
    fill = om.submit_exit("SENSEX2572575000CE", 20)
    assert fill.status == "filled"
    assert fill.price == 98.7


def test_paper_entry_with_no_kite_fills_with_none_price():
    om = PaperOrderManager(kite=None)
    fill = om.submit_entry("SENSEX2572575000CE", 20)
    assert fill.status == "filled"
    assert fill.price is None


def test_paper_entry_with_no_symbol_fills_with_none_price():
    om = PaperOrderManager(kite=_FakeKite(123.45))
    fill = om.submit_entry(None, 20)
    assert fill.status == "filled"
    assert fill.price is None


def test_paper_entry_quote_failure_fills_with_none_price():
    class _BrokenKite:
        def quote(self, symbols):
            raise RuntimeError("network error")

    om = PaperOrderManager(kite=_BrokenKite())
    fill = om.submit_entry("SENSEX2572575000CE", 20)
    assert fill.status == "filled"
    assert fill.price is None


from execution.order_manager import LiveOrderManager


class _FakeKiteFilled:
    def __init__(self):
        self.placed = []

    def place_order(self, **kwargs):
        self.placed.append(kwargs)
        return "order123"

    def order_history(self, order_id):
        return [{"status": "OPEN"}, {"status": "COMPLETE", "average_price": 145.5}]


def test_live_entry_fills_on_complete(monkeypatch):
    monkeypatch.setattr("execution.order_manager.time.sleep", lambda s: None)
    om = LiveOrderManager(kite=_FakeKiteFilled())
    fill = om.submit_entry("SENSEX2572575000CE", 20)
    assert fill == Fill(status="filled", price=145.5, order_id="order123")


def test_live_entry_places_a_buy_market_order(monkeypatch):
    monkeypatch.setattr("execution.order_manager.time.sleep", lambda s: None)
    kite = _FakeKiteFilled()
    om = LiveOrderManager(kite=kite)
    om.submit_entry("SENSEX2572575000CE", 20)
    assert kite.placed[0]["transaction_type"] == "BUY"
    assert kite.placed[0]["quantity"] == 20
    assert kite.placed[0]["order_type"] == "MARKET"
    assert kite.placed[0]["exchange"] == "BFO"
    assert kite.placed[0]["tradingsymbol"] == "SENSEX2572575000CE"


def test_live_exit_places_a_sell_market_order(monkeypatch):
    monkeypatch.setattr("execution.order_manager.time.sleep", lambda s: None)
    kite = _FakeKiteFilled()
    om = LiveOrderManager(kite=kite)
    om.submit_exit("SENSEX2572575000CE", 20)
    assert kite.placed[0]["transaction_type"] == "SELL"


class _FakeKiteRejected:
    def place_order(self, **kwargs):
        return "order999"

    def order_history(self, order_id):
        return [{"status": "REJECTED"}]


def test_live_entry_rejected_returns_rejected_fill(monkeypatch):
    monkeypatch.setattr("execution.order_manager.time.sleep", lambda s: None)
    om = LiveOrderManager(kite=_FakeKiteRejected())
    fill = om.submit_entry("SENSEX2572575000CE", 20)
    assert fill.status == "rejected"
    assert fill.price is None


class _FakeKiteNeverTerminal:
    def place_order(self, **kwargs):
        return "order555"

    def order_history(self, order_id):
        return [{"status": "OPEN"}]


def test_live_entry_timeout_returns_rejected_fill(monkeypatch):
    monkeypatch.setattr("execution.order_manager.time.sleep", lambda s: None)
    om = LiveOrderManager(kite=_FakeKiteNeverTerminal())
    fill = om.submit_entry("SENSEX2572575000CE", 20)
    assert fill.status == "rejected"


def test_live_entry_place_order_exception_returns_rejected_fill(monkeypatch):
    class _FakeKiteThrows:
        def place_order(self, **kwargs):
            raise RuntimeError("network down")

    om = LiveOrderManager(kite=_FakeKiteThrows())
    fill = om.submit_entry("SENSEX2572575000CE", 20)
    assert fill.status == "rejected"


def test_live_entry_with_no_symbol_is_rejected_without_placing_order():
    class _KiteShouldNotBeCalled:
        def place_order(self, **kwargs):
            raise AssertionError("should not place an order with no resolved symbol")

    om = LiveOrderManager(kite=_KiteShouldNotBeCalled())
    fill = om.submit_entry(None, 20)
    assert fill.status == "rejected"


def test_live_exit_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("execution.order_manager.time.sleep", lambda s: None)

    class _FlakyKite:
        def __init__(self):
            self.calls = 0

        def place_order(self, **kwargs):
            self.calls += 1
            return f"order{self.calls}"

        def order_history(self, order_id):
            if order_id == "order1":
                return [{"status": "REJECTED"}]
            return [{"status": "COMPLETE", "average_price": 100.0}]

    om = LiveOrderManager(kite=_FlakyKite())
    fill = om.submit_exit("SENSEX2572575000CE", 20)
    assert fill.status == "filled"
    assert fill.price == 100.0


def test_live_exit_exhausts_retries_and_logs_critical(monkeypatch, caplog):
    import logging
    monkeypatch.setattr("execution.order_manager.time.sleep", lambda s: None)

    om = LiveOrderManager(kite=_FakeKiteRejected())
    with caplog.at_level(logging.CRITICAL, logger="execution.order_manager"):
        fill = om.submit_exit("SENSEX2572575000CE", 20)
    assert fill.status == "rejected"
    assert any("Manual intervention required" in r.message for r in caplog.records)
