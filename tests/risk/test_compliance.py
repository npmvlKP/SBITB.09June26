"""Tests for src/risk/compliance.py — SEBI compliance constants and validation."""

from __future__ import annotations

from src.risk.compliance import (
    COMPLIANCE,
    SEBICompliance,
    is_algo_registration_required,
    validate_order_tag,
)


class TestSEBICompliance:
    """Verify compliance constants match SEBI/NSE circulars."""

    def test_ops_threshold_is_10(self) -> None:
        """NSE/INVG/67858: 10 OPS threshold for unregistered client algos."""
        assert COMPLIANCE.OPS_REGISTRATION_THRESHOLD == 10

    def test_no_500ms_resting_time_constant(self) -> None:
        """500ms resting time was PROPOSED (2016) but NOT implemented.
        No constant must exist for it."""
        for attr in dir(COMPLIANCE):
            if "500" in attr.lower() or "resting" in attr.lower():
                pytest.fail(
                    f"Found prohibited 500ms resting time attribute: {attr}"
                )

    def test_zerodha_rate_limits(self) -> None:
        assert COMPLIANCE.ZERODHA_RATE_LIMIT_PER_SEC == 10
        assert COMPLIANCE.ZERODHA_RATE_LIMIT_PER_MIN == 400
        assert COMPLIANCE.ZERODHA_RATE_LIMIT_PER_DAY == 5000

    def test_audit_retention_7_years(self) -> None:
        assert COMPLIANCE.AUDIT_RETENTION_YEARS == 7

    def test_static_ip_and_oauth_required(self) -> None:
        assert COMPLIANCE.STATIC_IP_REQUIRED is True
        assert COMPLIANCE.OAUTH_2FA_REQUIRED is True
        assert COMPLIANCE.NO_OPEN_APIS is True

    def test_regulatory_refs_include_key_circulars(self) -> None:
        refs = COMPLIANCE.REGULATORY_REFS
        assert "SEBI_2025_RETAIL_ALGO" in refs
        assert "NSE_2025_ATF" in refs
        assert refs["SEBI_2025_RETAIL_ALGO"] == (
            "SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013"
        )
        assert refs["NSE_2025_ATF"] == "NSE/INVG/67858"


class TestValidateOrderTag:
    def test_valid_alphanumeric_tag(self) -> None:
        assert validate_order_tag("MOMENTUM:V1") is True

    def test_empty_tag_rejected(self) -> None:
        assert validate_order_tag("") is False

    def test_tag_exceeds_max_length(self) -> None:
        assert validate_order_tag("A" * 21) is False

    def test_tag_at_max_length(self) -> None:
        assert validate_order_tag("A" * 20) is True


class TestIsAlgoRegistrationRequired:
    def test_below_threshold_no_registration(self) -> None:
        assert is_algo_registration_required(9) is False

    def test_at_threshold_no_registration(self) -> None:
        """At exactly 10 OPS, no registration required per NSE."""
        assert is_algo_registration_required(10) is False

    def test_above_threshold_requires_registration(self) -> None:
        assert is_algo_registration_required(11) is True


import pytest
