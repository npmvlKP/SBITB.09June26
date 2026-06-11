"""Emergency halt — 3 activation paths.

Paths:
  1. Keyboard/CLI — ``activate_kill_switch(level)``
  2. Telegram     — future integration (handler stub)
  3. REST API     — future integration (endpoint stub)

Kill switch must be INACTIVE before any order is placed.
After activation, manual re-enable is required (never auto-resume).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

import structlog

from config.settings import KillSwitchLevel

logger = structlog.get_logger(__name__)

IST_OFFSET = timezone(timedelta(hours=5, minutes=30))


class KillSwitchPath(StrEnum):
    CLI = "CLI"
    TELEGRAM = "TELEGRAM"
    REST_API = "REST_API"


class KillSwitchError(Exception):
    """Raised when an order is attempted while kill switch is active."""


class KillSwitch:
    """3-path emergency kill switch.

    Levels:
      INACTIVE — normal operation
      THROTTLE — reduce order rate to 10 % of normal
      PAUSE    — no new orders; existing orders remain open
      KILL     — cancel ALL open orders + disable new order placement
    """

    def __init__(self) -> None:
        self._level: KillSwitchLevel = KillSwitchLevel.INACTIVE
        self._activation_time: datetime | None = None
        self._activation_path: KillSwitchPath | None = None
        self._activation_reason: str = ""
        self._order_count_at_activation: int = 0
        self._log: list[dict[str, Any]] = []

    @property
    def level(self) -> KillSwitchLevel:
        return self._level

    @property
    def is_active(self) -> bool:
        return self._level != KillSwitchLevel.INACTIVE

    @property
    def activation_time(self) -> datetime | None:
        return self._activation_time

    def activate(
        self,
        level: KillSwitchLevel,
        path: KillSwitchPath = KillSwitchPath.CLI,
        reason: str = "",
        order_count: int = 0,
    ) -> None:
        """Activate kill switch at the given level."""
        if level == KillSwitchLevel.INACTIVE:
            logger.warning("kill_switch.activate_noop", level=level.value)
            return

        now = datetime.now(tz=UTC)

        self._level = level
        self._activation_time = now
        self._activation_path = path
        self._activation_reason = reason
        self._order_count_at_activation = order_count

        event = {
            "timestamp": now.isoformat(),
            "level": level.value,
            "path": path.value,
            "reason": reason,
            "order_count": order_count,
        }
        self._log.append(event)

        logger.critical(
            "kill_switch.activated",
            level=level.value,
            path=path.value,
            reason=reason,
        )

    def deactivate(self, reason: str = "manual_reset") -> None:
        """Deactivate kill switch — requires explicit manual action."""
        if not self.is_active:
            logger.warning("kill_switch.deactivate_noop")
            return

        now = datetime.now(tz=UTC)
        event = {
            "timestamp": now.isoformat(),
            "action": "DEACTIVATED",
            "previous_level": self._level.value,
            "reason": reason,
        }
        self._log.append(event)

        logger.info(
            "kill_switch.deactivated",
            previous_level=self._level.value,
            reason=reason,
        )

        self._level = KillSwitchLevel.INACTIVE
        self._activation_time = None
        self._activation_path = None
        self._activation_reason = ""

    def check_order_allowed(self) -> bool:
        """Return True if new orders are permitted at current level."""
        if self._level == KillSwitchLevel.INACTIVE:
            return True
        return self._level == KillSwitchLevel.THROTTLE

    def get_throttle_factor(self) -> float:
        """Return order rate multiplier for current level.

        INACTIVE -> 1.0, THROTTLE -> 0.1, PAUSE/KILL -> 0.0
        """
        factors: dict[KillSwitchLevel, float] = {
            KillSwitchLevel.INACTIVE: 1.0,
            KillSwitchLevel.THROTTLE: 0.1,
            KillSwitchLevel.PAUSE: 0.0,
            KillSwitchLevel.KILL: 0.0,
        }
        return factors.get(self._level, 0.0)

    def guard(self) -> None:
        """Raise KillSwitchError if orders are not allowed."""
        if not self.check_order_allowed():
            raise KillSwitchError(
                f"Kill switch active at level {self._level.value}. "
                f"Reason: {self._activation_reason}. "
                f"Activated at: {self._activation_time}"
            )

    def get_log(self) -> list[dict[str, Any]]:
        """Return immutable copy of activation log."""
        return list(self._log)
