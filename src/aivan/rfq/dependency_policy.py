"""Dependency failure policy.

Turns concrete dependency failures (language-skill down, GLTG down, giraffe-db
graph persistence failed, OpenClaw outbound failed, external model API disabled,
unknown backend exception) into structured recovery states with a user-facing
operator message — never a generic ``backend error, try again later`` for a
normal RFQ input (PRD §8).
"""

from __future__ import annotations

from pydantic import BaseModel

from aivan.llm.policy import (
    ExternalModelApiRequiresApprovalError,
    LocalModelUnavailableError,
)
from aivan.integrations.gltg import GLTGUnavailableError
from aivan.integrations.language_skill import LanguageSkillUnavailable


class DependencyStatus(BaseModel):
    name: str
    available: bool
    required_for_current_step: bool
    error: str | None = None
    recovery_action: str


class DependencyRecovery(BaseModel):
    """Structured outcome for a dependency failure."""

    dependency: str
    action: str
    blocked_reason: str
    operator_message_en: str
    operator_message_zh: str
    manual_review_required: bool = False

    def operator_message(self, zh: bool) -> str:
        return self.operator_message_zh if zh else self.operator_message_en


def classify_exception(exc: BaseException, *, step: str = "") -> DependencyRecovery:
    """Map an exception raised during RFQ execution to a recovery state."""
    if isinstance(exc, ExternalModelApiRequiresApprovalError):
        return DependencyRecovery(
            dependency="external_model_api",
            action="pending_external_model_approval",
            blocked_reason=str(exc),
            operator_message_en=(
                "This step could use an external model, but external model APIs "
                "are disabled in the private-domain baseline. AIVAN continued "
                "without it. Approve an external model call to increase strength."
            ),
            operator_message_zh=(
                "此步骤本可调用外部模型，但私域基线已禁用外部模型 API，"
                "AIVAN 已在不调用外部模型的情况下继续。如需增强能力，请审批外部模型调用。"
            ),
        )
    if isinstance(exc, LocalModelUnavailableError):
        return DependencyRecovery(
            dependency="local_model",
            action="reduced_strength_local_model_unavailable",
            blocked_reason=str(exc),
            operator_message_en=(
                "The private-domain local model is currently unavailable. AIVAN "
                "continued in reduced-strength mode using deterministic extraction "
                "and preserved the raw message. It did NOT fall back to any cloud "
                "model. Confirm canonical fields to proceed."
            ),
            operator_message_zh=(
                "私域本地模型当前不可用。AIVAN 已切换到降级模式（仅确定性抽取），"
                "并保留原文，未回退到任何云端模型。请确认关键字段后继续。"
            ),
            manual_review_required=True,
        )
    if isinstance(exc, LanguageSkillUnavailable):
        return DependencyRecovery(
            dependency="language_skill",
            action="pending_requirement_confirmation",
            blocked_reason=str(exc),
            operator_message_en=(
                "AIVAN could not canonicalize this RFQ (language service "
                "unavailable). The raw message was preserved. Please confirm the "
                "product and destination before AIVAN proceeds."
            ),
            operator_message_zh=(
                "语言服务暂不可用，AIVAN 无法规范化此询价，已保留原文。"
                "请先确认产品与目的地，AIVAN 再继续。"
            ),
            manual_review_required=True,
        )
    if isinstance(exc, GLTGUnavailableError):
        return DependencyRecovery(
            dependency="gltg",
            action="pending_dependency_recovery",
            blocked_reason=str(exc),
            operator_message_en=(
                "AIVAN structured the RFQ, but GLTG is currently unavailable. No "
                "supplier messages were sent. Please retry GLTG or continue with "
                "manual review."
            ),
            operator_message_zh=(
                "AIVAN 已整理该询价，但 GLTG 当前不可用，未发送任何供应商邮件。"
                "请稍后重试 GLTG，或转人工审核。"
            ),
            manual_review_required=True,
        )
    return DependencyRecovery(
        dependency="unknown_backend",
        action="pending_dependency_recovery",
        blocked_reason=f"{exc.__class__.__name__}: {exc}",
        operator_message_en=(
            "AIVAN hit an unexpected internal error while processing this RFQ and "
            "did not send any messages. The RFQ was preserved for retry/manual "
            "review."
        ),
        operator_message_zh=(
            "AIVAN 处理该询价时遇到意外内部错误，未发送任何消息。"
            "该询价已保留，可稍后重试或转人工审核。"
        ),
        manual_review_required=True,
    )
