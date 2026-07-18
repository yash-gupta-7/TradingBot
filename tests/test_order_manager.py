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
