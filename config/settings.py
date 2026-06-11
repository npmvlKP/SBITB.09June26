from __future__ import annotations

from decimal import Decimal
from enum import Enum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Segment(str, Enum):
    NFO = "NFO"
    CDS = "CDS"
    MCX = "MCX"
    NSE = "NSE"


class KillSwitchLevel(str, Enum):
    INACTIVE = "INACTIVE"
    THROTTLE = "THROTTLE"
    PAUSE = "PAUSE"
    KILL = "KILL"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / "secrets.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project_name: str = "SBITB-090626"

    kite_api_key: str = ""
    kite_api_secret: str = ""
    kite_access_token: str = ""

    database_url: str = "postgresql+asyncpg://bot:bot@localhost:5432/sbitb"

    tz: str = "Asia/Kolkata"

    max_order_value: Decimal = Decimal("200000")
    max_daily_orders: int = 2000
    max_orders_per_second: int = 3
    max_orders_per_minute: int = 200
    max_position_per_symbol: Decimal = Decimal("500000")
    max_total_exposure: Decimal = Decimal("2000000")
    margin_utilization_threshold: Decimal = Decimal("0.80")
    daily_loss_limit: Decimal = Decimal("50000")
    max_order_rejections_per_minute: int = 10

    ops_registration_threshold: int = 10

    trading_start_hour: int = 9
    trading_start_minute: int = 15
    trading_end_hour: int = 15
    trading_end_minute: int = 30

    allowed_segments: list[Segment] = Field(
        default=[Segment.NFO, Segment.CDS]
    )

    audit_retention_years: int = 7
    audit_checksum_algorithm: str = "sha256"

    kill_switch_level: KillSwitchLevel = KillSwitchLevel.INACTIVE

    log_level: str = "INFO"


settings = Settings()
