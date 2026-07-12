# tests/test_config.py
from utils.config import load_config


def test_load_config_returns_expected_sections():
    cfg = load_config("config/config.yaml")
    assert "instrument" in cfg
    assert "indicators" in cfg
    assert "risk" in cfg
    assert cfg["risk"]["reward_risk_ratio"] == 2.0
