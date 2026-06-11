"""Tests for src/risk/kill_switch.py — 3-path emergency halt."""

from __future__ import annotations

import pytest

from config.settings import KillSwitchLevel
from src.risk.kill_switch import KillSwitch, KillSwitchError, KillSwitchPath


class TestKillSwitch:
    def test_initial_state_is_inactive(self, kill_switch: KillSwitch) -> None:
        assert kill_switch.level == KillSwitchLevel.INACTIVE
        assert kill_switch.is_active is False

    def test_activate_kill_level(self, kill_switch: KillSwitch) -> None:
        kill_switch.activate(
            KillSwitchLevel.KILL,
            path=KillSwitchPath.CLI,
            reason="runaway_algo",
        )
        assert kill_switch.level == KillSwitchLevel.KILL
        assert kill_switch.is_active is True
        assert kill_switch.activation_time is not None

    def test_activate_pause_blocks_orders(
        self, kill_switch: KillSwitch
    ) -> None:
        kill_switch.activate(
            KillSwitchLevel.PAUSE,
            path=KillSwitchPath.TELEGRAM,
            reason="manual_pause",
        )
        assert kill_switch.check_order_allowed() is False

    def test_throttle_allows_orders(self, kill_switch: KillSwitch) -> None:
        kill_switch.activate(
            KillSwitchLevel.THROTTLE,
            path=KillSwitchPath.REST_API,
            reason="approaching_limit",
        )
        assert kill_switch.check_order_allowed() is True
        assert kill_switch.get_throttle_factor() == 0.1

    def test_guard_raises_on_kill(self, kill_switch: KillSwitch) -> None:
        kill_switch.activate(
            KillSwitchLevel.KILL,
            reason="test",
        )
        with pytest.raises(KillSwitchError):
            kill_switch.guard()

    def test_deactivate_resets_state(self, kill_switch: KillSwitch) -> None:
        kill_switch.activate(KillSwitchLevel.PAUSE, reason="test")
        assert kill_switch.is_active is True
        kill_switch.deactivate()
        assert kill_switch.level == KillSwitchLevel.INACTIVE
        assert kill_switch.is_active is False
        assert kill_switch.activation_time is None

    def test_activation_log_recorded(self, kill_switch: KillSwitch) -> None:
        kill_switch.activate(KillSwitchLevel.KILL, reason="test")
        log = kill_switch.get_log()
        assert len(log) == 1
        assert log[0]["level"] == "KILL"
        assert log[0]["reason"] == "test"
