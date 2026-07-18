from datetime import datetime

from live.ticker_loop import _past_square_off


def test_past_square_off_true_after_time(monkeypatch):
    class _FixedDatetime(datetime):
        @classmethod
        def now(cls):
            return datetime(2026, 7, 18, 15, 21)

    monkeypatch.setattr("live.ticker_loop.datetime", _FixedDatetime)
    assert _past_square_off("15:20") is True


def test_past_square_off_false_before_time(monkeypatch):
    class _FixedDatetime(datetime):
        @classmethod
        def now(cls):
            return datetime(2026, 7, 18, 15, 19)

    monkeypatch.setattr("live.ticker_loop.datetime", _FixedDatetime)
    assert _past_square_off("15:20") is False
