# SPDX-License-Identifier: FSL-1.1-ALv2
"""Six-tier model routing configuration (Design §11.7)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml


class ModelTier(StrEnum):
    HIGH_CODING = "high_coding"
    HIGH_ANALYSIS = "high_analysis"
    MEDIUM = "medium"
    MEDIUM_VALUE = "medium_value"
    LOW_LOGS = "low_logs"
    SELF_HOSTED = "self_hosted"


class EndpointProtocol(StrEnum):
    OPENAI_COMPATIBLE = "openai_compatible"
    ANTHROPIC_NATIVE = "anthropic_native"
    GOOGLE_NATIVE = "google_native"


@dataclass(frozen=True)
class EndpointDescriptor:
    """A validated model endpoint descriptor."""

    id: str
    provider: str
    model: str
    protocol: EndpointProtocol
    base_url: str
    key_ref: str | None
    timeout_seconds: float = 60.0
    rank_source: str = "unranked"
    internal_golden_score: float | None = None


@dataclass(frozen=True)
class TierChain:
    """Ordered endpoint chain for a tier."""

    primary: str
    secondary: str | None = None
    cross_vendor: tuple[str, ...] = ()
    self_hosted: tuple[str, ...] = ()

    def ordered_ids(self) -> list[str]:
        """Deduplicated chain in cascade order."""
        seen: set[str] = set()
        result: list[str] = []
        for eid in [self.primary, self.secondary, *self.cross_vendor, *self.self_hosted]:
            if eid and eid not in seen:
                seen.add(eid)
                result.append(eid)
        return result


@dataclass(frozen=True)
class TierConfig:
    """Validated tier configuration with endpoint chains."""

    tiers: dict[ModelTier, TierChain]
    endpoints: dict[str, EndpointDescriptor]


def load_tier_config(path: str | Path) -> TierConfig:
    """Load and validate tier configuration from YAML."""
    path = Path(path)
    with open(path) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict) or "tiers" not in raw or "endpoints" not in raw:
        raise ValueError("Tier config must have 'tiers' and 'endpoints' keys")

    # Validate endpoints
    endpoints: dict[str, EndpointDescriptor] = {}
    for eid, edata in raw["endpoints"].items():
        protocol = edata.get("protocol", "")
        if protocol not in [p.value for p in EndpointProtocol]:
            raise ValueError(f"Endpoint {eid}: unknown protocol '{protocol}'")
        base_url = edata.get("base_url", "")
        if not base_url.startswith(("http://", "https://", "${")):
            raise ValueError(f"Endpoint {eid}: base_url must be absolute HTTP(S) URL")
        if "leaderboard_score" in edata or "vendor_score" in edata:
            raise ValueError(f"Endpoint {eid}: vendor leaderboard score fields are forbidden")
        endpoints[eid] = EndpointDescriptor(
            id=eid,
            provider=edata["provider"],
            model=edata["model"],
            protocol=EndpointProtocol(protocol),
            base_url=base_url,
            key_ref=edata.get("key_ref"),
            timeout_seconds=edata.get("timeout_seconds", 60.0),
            rank_source=edata.get("rank_source", "unranked"),
            internal_golden_score=edata.get("internal_golden_score"),
        )

    # Validate tiers
    tiers: dict[ModelTier, TierChain] = {}
    for tname, tdata in raw["tiers"].items():
        tier = ModelTier(tname)
        primary = tdata["primary"]
        if primary not in endpoints:
            raise ValueError(f"Tier {tname}: primary '{primary}' not in endpoints")
        secondary = tdata.get("secondary")
        if secondary and secondary not in endpoints:
            raise ValueError(f"Tier {tname}: secondary '{secondary}' not in endpoints")
        cross = tuple(tdata.get("cross_vendor", []))
        self_hosted = tuple(tdata.get("self_hosted", []))
        tiers[tier] = TierChain(
            primary=primary,
            secondary=secondary,
            cross_vendor=cross,
            self_hosted=self_hosted,
        )

    return TierConfig(tiers=tiers, endpoints=endpoints)
