"""SEBI compliance enforcement constants and validation rules.

References:
  - SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013 (Feb 4, 2025)
  - NSE/INVG/67858 (May 5, 2025)
  - SEBI/HO/MRD/DP/CIR/P/2018/62 (Apr 9, 2018)
  - CIR/MRD/DP/09/2012 (Mar 30, 2012)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

_REGULATORY_REFS: dict[str, str] = {
    "SEBI_2012_ALGO": "CIR/MRD/DP/09/2012",
    "SEBI_2018_STRENGTHENING": "SEBI/HO/MRD/DP/CIR/P/2018/62",
    "SEBI_2025_RETAIL_ALGO": (
        "SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013"
    ),
    "NSE_2025_ATF": "NSE/INVG/67858",
    "NSE_2026_CLIENT_API": "NSE/INVG/73992",
    "SEBI_2020_OTR": "SEBI/HO/MRD1/DSAP/CIR/P/2020/107",
    "SEBI_2024_AI_ML": "SEBI/HO/MRD/DOP1/CIR/P/2024/13",
}


@dataclass(frozen=True)
class SEBICompliance:
    """Immutable SEBI compliance thresholds and regulatory references.

    IMPORTANT CORRECTIONS applied per latest circulars:
    - 500ms resting time was PROPOSED (2016 discussion paper) but NOT
      implemented in the 2018 circular (SEBI/HO/MRD/DP/CIR/P/2018/62).
      No constant or rule is defined for it.
    - Algo ID tagging is the BROKER's responsibility per
      SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013. The exchange provides
      the unique algo ID; the broker tags orders server-side. Our `tag`
      field in Kite API is for our own audit trail/attribution only.
    - OPS registration threshold = 10 per NSE/INVG/67858 (May 5, 2025).
      Below this, no registration needed; above, must register algo
      with exchange through broker.
    """

    OPS_REGISTRATION_THRESHOLD: int = 10

    ZERODHA_RATE_LIMIT_PER_SEC: int = 10
    ZERODHA_RATE_LIMIT_PER_MIN: int = 400
    ZERODHA_RATE_LIMIT_PER_DAY: int = 5000

    SELF_IMPOSED_OPS_LIMIT: int = 3

    AUDIT_RETENTION_YEARS: int = 7
    AUDIT_CHECKSUM_ALGORITHM: str = "sha256"

    OTR_EXEMPTION_BAND_BPS: Decimal = Decimal("0.75")

    STATIC_IP_REQUIRED: bool = True
    OAUTH_2FA_REQUIRED: bool = True
    NO_OPEN_APIS: bool = True

    KILL_SWITCH_EXCHANGE_CONTROL: bool = True

    BLACK_BOX_ALGO_RA_REGISTRATION: bool = True

    TAG_MAX_LENGTH: int = 20

    REGULATORY_REFS: dict[str, str] = field(
        default_factory=lambda: dict(_REGULATORY_REFS)
    )


COMPLIANCE = SEBICompliance()


def validate_order_tag(tag: str) -> bool:
    """Validate our internal order tag per Kite API constraints.

    The `tag` field is for our audit trail/attribution only.
    Exchange-mandated algo ID tagging is the broker's responsibility.
    """
    if not tag:
        return False
    if len(tag) > COMPLIANCE.TAG_MAX_LENGTH:
        return False
    return tag.isalnum() or all(c.isalnum() or c == ":" for c in tag)


def is_algo_registration_required(ops: int) -> bool:
    """Return True if the given OPS exceeds the registration threshold.

    Per NSE/INVG/67858: client-generated algos at or below
    OPS_REGISTRATION_THRESHOLD need NOT be registered.
    """
    return ops > COMPLIANCE.OPS_REGISTRATION_THRESHOLD
