"""Faithful in-memory fake of the standalone GLTG HTTP API for tests.

Provides an ``httpx.MockTransport`` that mirrors the GLTG endpoints
deterministically, so AIVAN's unit tests exercise the real HTTP client and
mapping code without a live GLTG server.
"""

from __future__ import annotations

import json
import math

import httpx


def _baseline_total(quantity: int, supplier: dict) -> float:
    # Mirrors GLTG baseline shape closely enough for assertions.
    stage = (
        (supplier.get("material_ready_days") or 0)
        + (supplier.get("production_days") or 0)
        + (supplier.get("qc_days") or 0)
        + (supplier.get("logistics_days") or 0)
    )
    if stage > 0:
        cap = supplier.get("capacity_per_day") or 0
        if cap and quantity:
            stage = max(stage, math.ceil(quantity / cap))
        return float(stage)
    # requirement-level: synthesize a baseline
    cap = supplier.get("capacity_per_day") or 500
    production = max(math.ceil(quantity / max(int(cap * 0.85), 1)), 1) + 2
    return float(17 + production + 6 + 30)  # material + production + qc + logistics


def _response_penalty(override: dict) -> float:
    """Mirror GLTG: speed + completeness each up to 0.15 (max 0.30)."""
    speed = (1.0 - float(override.get("response_speed_score", 1.0))) * 0.15
    completeness = (1.0 - float(override.get("completeness_score", 1.0))) * 0.15
    return round(speed + completeness, 6)


def _effective_supplier(supplier: dict, override: dict | None) -> dict:
    """Apply available_capacity_per_day override to the supplier's capacity."""
    if not override:
        return supplier
    cap = override.get("available_capacity_per_day")
    if cap:
        supplier = {**supplier, "capacity_per_day": cap}
    return supplier


def _estimate(payload: dict) -> dict:
    order = payload.get("order", {})
    suppliers = payload.get("suppliers", []) or []
    overrides = payload.get("supplier_state_overrides") or {}
    quantity = order.get("quantity", 0) or 0
    deadline = order.get("deadline_days")
    n = len(suppliers)
    warnings = []
    if n == 0:
        return {
            "status": "ok",
            "estimated_lead_time_days": None,
            "earliest_delivery_date": None,
            "feasible": False,
            "supplier_count": 0,
            "selected_supplier_id": None,
            "p50_days": None,
            "p80_days": None,
            "p90_days": None,
            "minimum_feasible_days": None,
            "risk_level": "unknown",
            "warnings": [{"code": "NO_SUPPLIERS", "message": "No suppliers provided."}],
            "calculation_trace": [],
        }
    traces = []
    totals = []
    for raw_s in suppliers:
        sid = raw_s.get("supplier_id", "?")
        override = overrides.get(sid)
        s = _effective_supplier(raw_s, override)
        # load_factor stretches the non-production portion of the lead time.
        load_factor = float(override.get("load_factor", 1.0)) if override else 1.0
        total = _baseline_total(quantity, s) * load_factor
        totals.append((total, s))
        traces.append(
            {
                "supplier_id": sid,
                "material_ready_days": s.get("material_ready_days") or 17,
                "production_days": s.get("production_days") or 0,
                "capacity_adjusted_production_days": s.get("production_days")
                or (max(math.ceil(quantity / max(int((s.get("capacity_per_day") or 500) * 0.85), 1)), 1) + 2),
                "qc_days": s.get("qc_days") or 6,
                "logistics_days": s.get("logistics_days") or 30,
                "total_lead_time_days": total,
                "confidence": s.get("confidence", 0.5),
                "feasible": deadline is None or total <= deadline,
                "response_penalty": _response_penalty(override) if override else 0.0,
                "supplier_risk_flags": (
                    {sid: list(override.get("risk_flags", []))}
                    if override and override.get("risk_flags")
                    else {}
                ),
            }
        )
    totals.sort(key=lambda t: t[0])
    total, selected = totals[0]
    conf = selected.get("confidence", 0.5)
    p50 = float(round(total))
    p80 = float(math.ceil(total * (1.10 + 0.20 * (1 - conf))))
    p90 = float(math.ceil(total * (1.20 + 0.35 * (1 - conf))))
    minimum = float(math.floor(total * 0.85))
    feasible = deadline is None or total <= deadline
    if deadline is None:
        risk = "low" if conf >= 0.75 else "medium" if conf >= 0.5 else "high"
    elif total > deadline:
        risk = "high"
    elif p80 > deadline:
        risk = "medium"
    else:
        risk = "low"
    if n == 1:
        warnings.append({"code": "LIMITED_COMPARISON", "message": "one supplier"})
    elif n == 2:
        warnings.append({"code": "LIMITED_SUPPLIER_POOL", "message": "two suppliers"})
    return {
        "status": "ok",
        "estimated_lead_time_days": total,
        "earliest_delivery_date": None,
        "feasible": feasible,
        "supplier_count": n,
        "selected_supplier_id": selected.get("supplier_id"),
        "p50_days": p50,
        "p80_days": p80,
        "p90_days": p90,
        "minimum_feasible_days": minimum,
        "risk_level": risk,
        "warnings": warnings,
        "calculation_trace": traces,
    }


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/health":
        return httpx.Response(200, json={"status": "ok", "service": "gltg"})
    if path == "/version":
        return httpx.Response(200, json={"service": "gltg", "version": "1.0.0", "api_version": "v1"})
    payload = json.loads(request.content.decode() or "{}")
    if path == "/v1/lead-time/estimate":
        return httpx.Response(200, json=_estimate(payload))
    if path == "/v1/reforecast":
        est = _estimate(payload)
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "baseline_lead_time_days": est["estimated_lead_time_days"],
                "updated_lead_time_days": est["estimated_lead_time_days"],
                "delta_days": 0,
                "feasible": est["feasible"],
                "supplier_count": est["supplier_count"],
                "selected_supplier_id": est["selected_supplier_id"],
                "applied_events": [],
                "warnings": est["warnings"],
                "calculation_trace": est["calculation_trace"],
            },
        )
    if path == "/v1/paths/enumerate":
        est = _estimate(payload)
        # committable lead time is primary; response penalty breaks ties so a
        # slow/no-response supplier ranks below an equal-date peer (mirrors GLTG).
        ordered = sorted(
            est["calculation_trace"],
            key=lambda t: (
                0 if t["feasible"] else 1,
                t["total_lead_time_days"],
                t.get("response_penalty", 0.0),
                -t.get("confidence", 0.5),
                t["supplier_id"],
            ),
        )
        paths = []
        for i, t in enumerate(ordered, start=1):
            paths.append(
                {
                    "path_id": f"single:{t['supplier_id']}",
                    "rank": i,
                    "mode": "SINGLE_SOURCE",
                    "supplier_ids": [t["supplier_id"]],
                    "estimated_lead_time_days": t["total_lead_time_days"],
                    "earliest_delivery_date": None,
                    "feasible": t["feasible"],
                    "confidence": t["confidence"],
                    "score": round(max(0.0, 1.0 - t.get("response_penalty", 0.0)), 4),
                    "supplier_risk_flags": t.get("supplier_risk_flags", {}),
                    "warnings": [],
                }
            )
        return httpx.Response(
            200, json={"status": "ok", "supplier_count": est["supplier_count"], "paths": paths, "warnings": est["warnings"]}
        )
    return httpx.Response(404, json={"detail": "not found"})


def mock_transport() -> httpx.MockTransport:
    return httpx.MockTransport(handler)
