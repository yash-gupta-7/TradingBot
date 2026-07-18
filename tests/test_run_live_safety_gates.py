import argparse

import pytest

from live.run_live import _check_safety_gates


def _args(live=True):
    ns = argparse.Namespace()
    ns.live = live
    return ns


def test_all_gates_pass_does_not_raise():
    cfg = {"execution": {"mode": "live", "confirm_live": True}}
    _check_safety_gates(_args(live=True), cfg)  # should not raise


def test_missing_cli_flag_blocks():
    cfg = {"execution": {"mode": "live", "confirm_live": True}}
    with pytest.raises(SystemExit, match="--live"):
        _check_safety_gates(_args(live=False), cfg)


def test_missing_config_mode_blocks():
    cfg = {"execution": {"mode": "paper", "confirm_live": True}}
    with pytest.raises(SystemExit, match="execution.mode"):
        _check_safety_gates(_args(live=True), cfg)


def test_missing_confirm_live_blocks():
    cfg = {"execution": {"mode": "live", "confirm_live": False}}
    with pytest.raises(SystemExit, match="confirm_live"):
        _check_safety_gates(_args(live=True), cfg)


def test_missing_execution_section_blocks():
    cfg = {}
    with pytest.raises(SystemExit):
        _check_safety_gates(_args(live=True), cfg)
