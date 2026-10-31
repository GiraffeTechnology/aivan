"""Stable business input identity for replaying an existing GPM analysis."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def request_fingerprint(payload: dict[str, Any], *, tenant_id: str,
                        actor_id: str | None, actor_role: str | None) -> str:
    # Correlation identifies a transport attempt, not a different quotation.
    inputs = {**payload, "evidence_ids": payload.get("evidence_ids") or []}
    # HTTP JSON may encode 10 as an integer while Pydantic stores 10.0.
    # Normalize declared numeric inputs, not arbitrary strings or model output.
    for key in ("supplier_quote", "buyer_unit_price", "buyer_total", "supplier_total", "margin_rate"):
        if inputs.get(key) is not None:
            inputs[key] = float(inputs[key])
    canonical = json.dumps({"tenant_id": tenant_id, "actor_id": actor_id,
                            "actor_role": actor_role, "inputs": inputs},
                           sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def matches_request(packet: dict, payload: dict, *, tenant_id: str,
                    actor_id: str | None, actor_role: str | None) -> bool:
    if any(key not in packet for key in payload):
        return False
    stored_tenant = packet.get("tenant_id")
    if not isinstance(stored_tenant, str) or stored_tenant != tenant_id:
        return False
    stored = {key: packet[key] for key in payload}
    try:
        evidence = stored.get("evidence_ids")
        if isinstance(evidence, str):
            stored["evidence_ids"] = json.loads(evidence)
        return request_fingerprint(stored, tenant_id=stored_tenant,
                                   actor_id=packet.get("actor_id"), actor_role=packet.get("actor_role")) == request_fingerprint(
            payload, tenant_id=tenant_id, actor_id=actor_id, actor_role=actor_role)
    except (TypeError, ValueError):
        return False
