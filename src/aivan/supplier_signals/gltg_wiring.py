"""Task 3 wiring: signals -> GLTG supplier_state_overrides, and GLTG risk flags
-> buyer-facing decision-packet warnings.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aivan.supplier_signals.adjustment import load_factor
from aivan.supplier_signals.models import RiskFlag, SupplierStateSignal

# Buyer-facing warning text for each risk flag (Simplified Chinese).
RISK_FLAG_DISPLAY: dict[str, str] = {
    RiskFlag.HIGH_LOAD.value: "⚠️ HIGH_LOAD — 供应商当前产能紧张",
    RiskFlag.SLOW_RESPONSE.value: "⚠️ SLOW_RESPONSE — 本次询盘响应时间明显慢于历史均值",
    RiskFlag.INCOMPLETE_RESPONSE.value: "⚠️ INCOMPLETE_RESPONSE — 供应商回复信息不完整",
    RiskFlag.LATE_START.value: "⚠️ LATE_START — 最早开始日期超出预期30天",
    RiskFlag.NO_RESPONSE.value: "⚠️ NO_RESPONSE — 供应商未在24工作小时内回复",
}


def signal_to_override(signal: SupplierStateSignal) -> dict:
    """Map one assembled signal onto a GLTG supplier_state_overrides entry.

    Capacity is passed through directly when extracted; load_factor is derived
    from load_level (Phase 1 rule). Empty/None fields are omitted so each
    override stays minimal and GLTG keeps its historical baseline for them.
    """
    override: dict = {
        "load_factor": load_factor(signal),
        "response_speed_score": signal.response_speed_score,
        "completeness_score": signal.completeness_score,
        "risk_flags": [f.value for f in signal.risk_flags],
    }
    if signal.available_capacity_per_day is not None:
        override["available_capacity_per_day"] = signal.available_capacity_per_day
    if signal.earliest_available_date is not None:
        override["earliest_available_date"] = signal.earliest_available_date.isoformat()
    return override


def build_overrides(signals: dict[str, SupplierStateSignal]) -> dict[str, dict]:
    """Build the supplier_state_overrides map for GLTG from per-supplier signals.

    Suppliers with no signal are simply absent -> GLTG falls back to history.
    """
    return {sid: signal_to_override(sig) for sid, sig in signals.items()}


def render_risk_flag_warnings(flags: list[str]) -> list[str]:
    """Turn GLTG risk-flag codes into buyer-facing ⚠️ warning lines."""
    return [RISK_FLAG_DISPLAY.get(code, f"⚠️ {code}") for code in flags]


@dataclass
class DecisionOption:
    """One ranked supplier option as shown to the buyer."""

    supplier_id: str
    rank: int
    estimated_lead_time_days: float
    feasible: bool
    score: float
    risk_flags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class DecisionPacket:
    """Buyer-facing decision packet built from a GLTG enumerate response."""

    options: list[DecisionOption] = field(default_factory=list)


def enumerate_with_signals(
    order: dict,
    suppliers: list[dict],
    signals: dict[str, SupplierStateSignal],
    client=None,
    constraints: dict | None = None,
) -> DecisionPacket:
    """End-to-end: signals -> GLTG enumerate with overrides -> decision packet.

    Raises GLTGUnavailableError on GLTG failure (never invents a result).
    """
    from aivan.integrations.gltg import GLTGUnavailableError
    from aivan.integrations.gltg_client import GLTGClient

    client = client or GLTGClient()
    overrides = build_overrides(signals)
    result = client.enumerate_paths(
        order,
        suppliers,
        constraints or {},
        supplier_state_overrides=overrides or None,
    )
    if not result.ok or result.data is None:
        raise GLTGUnavailableError(result.error or "GLTG returned no data")
    return decision_packet_from_paths(result.data.get("paths", []))


def decision_packet_from_paths(paths: list[dict]) -> DecisionPacket:
    """Map a GLTG /v1/paths/enumerate ``paths`` list into a DecisionPacket.

    Each option's supplier_risk_flags (keyed by supplier_id in the GLTG response)
    are flattened and rendered as visible warnings on that supplier's option.
    """
    options: list[DecisionOption] = []
    for path in paths:
        supplier_ids = path.get("supplier_ids", []) or []
        supplier_id = supplier_ids[0] if supplier_ids else path.get("path_id", "")
        flag_map = path.get("supplier_risk_flags", {}) or {}
        flags = [code for codes in flag_map.values() for code in codes]
        options.append(
            DecisionOption(
                supplier_id=supplier_id,
                rank=int(path.get("rank", 0) or 0),
                estimated_lead_time_days=float(path.get("estimated_lead_time_days", 0) or 0),
                feasible=bool(path.get("feasible", False)),
                score=float(path.get("score", 0) or 0),
                risk_flags=flags,
                warnings=render_risk_flag_warnings(flags),
            )
        )
    return DecisionPacket(options=options)
