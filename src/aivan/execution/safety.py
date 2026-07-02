"""Centralized execution readiness gates.

This is the single place that decides whether an RFQ requirement is safe to
execute against. Nothing downstream — strategy interpretation, giraffe-db
context lookup, GLTG simulation, graph persistence, or supplier drafts — may run
until :func:`evaluate_requirement_readiness` reports ``ready`` (PRD §6).

A requirement is executable only when it has:
    * quantity,
    * a product identity (name/type/category) from an authoritative source,
    * a canonical destination from an authoritative source,
    * a delivery target (days or deadline).

Raw-text-only product/destination is treated as *missing*: it triggers human
confirmation, never execution.
"""

from __future__ import annotations

from pydantic import BaseModel

from aivan.rfq import semantic_sources
from aivan.schemas.requirement import BuyerRequirement


class RequirementNotReady(RuntimeError):
    def __init__(self, missing_fields: list[str], reason: str):
        self.missing_fields = missing_fields
        self.reason = reason
        super().__init__(reason)


class SupplierSetNotReady(RuntimeError):
    def __init__(self, reason: str, feasibility: str = "none"):
        self.reason = reason
        self.feasibility = feasibility
        super().__init__(reason)


class ExecutionGateResult(BaseModel):
    ready: bool
    missing_fields: list[str] = []
    blocked_reason: str = ""
    next_action: str = "proceed"
    operator_message: str = ""


def _has_delivery_target(requirement: BuyerRequirement) -> bool:
    return requirement.delivery_days is not None or bool(requirement.delivery_deadline_iso)


def evaluate_requirement_readiness(requirement: BuyerRequirement) -> ExecutionGateResult:
    """Return the readiness verdict for a requirement.

    ``next_action`` is one of ``proceed``, ``pending_destination_confirmation``,
    ``pending_product_confirmation``, or ``pending_requirement_confirmation``.
    """
    missing: list[str] = []

    if requirement.quantity is None:
        missing.append("quantity")

    product_ok = semantic_sources.has_authoritative_product(requirement)
    if not product_ok:
        missing.append("product")

    destination_ok = semantic_sources.has_authoritative_destination(requirement)
    if not destination_ok:
        missing.append("destination")

    if not _has_delivery_target(requirement):
        missing.append("delivery")

    if not missing:
        return ExecutionGateResult(
            ready=True,
            missing_fields=[],
            blocked_reason="",
            next_action="proceed",
            operator_message="",
        )

    # Destination is the highest-signal blocker for a specific operator prompt.
    if "destination" in missing and destination_ok is False and requirement.quantity is not None and product_ok:
        next_action = "pending_destination_confirmation"
    elif missing == ["product"] or (not product_ok and requirement.quantity is not None and destination_ok):
        next_action = "pending_product_confirmation"
    else:
        next_action = "pending_requirement_confirmation"

    result = ExecutionGateResult(
        ready=False,
        missing_fields=missing,
        blocked_reason=f"Requirement not executable; missing/non-authoritative: {', '.join(missing)}.",
        next_action=next_action,
    )
    result.operator_message = build_confirmation_message(requirement, result)
    return result


def assert_ready_for_strategy(requirement: BuyerRequirement) -> None:
    _assert_ready(requirement, "strategy interpretation")


def assert_ready_for_gltg(requirement: BuyerRequirement) -> None:
    _assert_ready(requirement, "GLTG simulation")


def assert_ready_for_giraffe_graph(requirement: BuyerRequirement) -> None:
    _assert_ready(requirement, "giraffe-db graph persistence")


def assert_ready_for_supplier_drafts(
    requirement: BuyerRequirement, suppliers: list[dict]
) -> None:
    _assert_ready(requirement, "supplier draft creation")


def _assert_ready(requirement: BuyerRequirement, step: str) -> None:
    gate = evaluate_requirement_readiness(requirement)
    if not gate.ready:
        raise RequirementNotReady(
            missing_fields=gate.missing_fields,
            reason=f"{step} blocked: {gate.blocked_reason}",
        )


def evaluate_supplier_readiness(suppliers: list[dict]) -> tuple[str, bool]:
    """Classify a supplier candidate set. Returns (feasibility, ready).

    0 -> ("none", False); 1 -> ("single", False -> ask confirmation, not error);
    2 -> ("thin", True); 3+ -> ("sufficient", True). AIVAN never fabricates
    suppliers, and a count below 3 must never raise.
    """
    n = len([s for s in suppliers if s.get("email")])
    if n == 0:
        return "none", False
    if n == 1:
        return "single", False
    if n == 2:
        return "thin", True
    return "sufficient", True


# Feasibility -> operator action. A thin/sufficient set proceeds; a single
# supplier is a confirmation (single-supplier risk), never a hard error.
SUPPLIER_FEASIBILITY_ACTION = {
    "none": "pending_supplier_selection",
    "single": "pending_supplier_confirmation",
    "thin": "proceed",
    "sufficient": "proceed",
}


def supplier_action(suppliers: list[dict]) -> str:
    feasibility, _ = evaluate_supplier_readiness(suppliers)
    return SUPPLIER_FEASIBILITY_ACTION[feasibility]


# ---------------------------------------------------------------------- #
# Operator confirmation messages (language-matched, deterministic)
# ---------------------------------------------------------------------- #
def _is_chinese(requirement: BuyerRequirement) -> bool:
    if requirement.language == "zh":
        return True
    return any("一" <= ch <= "鿿" for ch in requirement.raw_text)


def build_confirmation_message(
    requirement: BuyerRequirement, gate: ExecutionGateResult
) -> str:
    """Render a deterministic, user-facing confirmation prompt for a blocked RFQ."""
    zh = _is_chinese(requirement)
    qty = requirement.quantity
    unit = requirement.quantity_unit
    days = requirement.delivery_days
    product_hint = (
        requirement.product_type
        or requirement.category
        or (requirement.extra.get("product_raw") if requirement.extra else "")
        or ""
    )
    dest_raw = (requirement.extra.get("destination_raw") if requirement.extra else "") or ""

    if "destination" in gate.missing_fields and gate.next_action == "pending_destination_confirmation":
        if zh:
            lines = ["RFQ 已记录，但目的地尚未确认："]
            if product_hint:
                lines.append(f"- 产品线索：{product_hint}")
            if qty is not None:
                lines.append(f"- 数量：{qty} {unit}")
            if days is not None:
                lines.append(f"- 目标交期：{days} 天")
            if dest_raw:
                lines.append(f"- 原文目的地线索：{dest_raw}")
            lines.append("")
            lines.append("请确认交货城市、港口、仓库或完整收货地址。")
            lines.append("在目的地确认前，AIVAN 不会运行 GLTG，也不会生成供应商询价草稿。")
            return "\n".join(lines)
        lines = ["RFQ recorded, but the destination is not yet confirmed:"]
        if product_hint:
            lines.append(f"- Product lead: {product_hint}")
        if qty is not None:
            lines.append(f"- Quantity: {qty} {unit}")
        if days is not None:
            lines.append(f"- Target delivery: {days} days")
        if dest_raw:
            lines.append(f"- Raw destination clue: {dest_raw}")
        lines.append("")
        lines.append("Please confirm the delivery city, port, warehouse, or full address.")
        lines.append("AIVAN will not run GLTG or create supplier drafts until the destination is confirmed.")
        return "\n".join(lines)

    # Generic requirement confirmation (missing several fields).
    label = {
        "quantity": ("数量", "quantity"),
        "product": ("产品", "product"),
        "destination": ("目的地", "destination"),
        "delivery": ("交期", "delivery target"),
    }
    if zh:
        need = "、".join(label[m][0] for m in gate.missing_fields if m in label)
        return (
            "RFQ 已记录，但以下关键信息尚未确认，请补充：\n"
            f"- 待确认：{need}\n\n"
            "在关键信息确认前，AIVAN 不会运行 GLTG，也不会生成供应商询价草稿。"
        )
    need = ", ".join(label[m][1] for m in gate.missing_fields if m in label)
    return (
        "RFQ recorded, but the following critical fields are not yet confirmed:\n"
        f"- Needed: {need}\n\n"
        "AIVAN will not run GLTG or create supplier drafts until these are confirmed."
    )
