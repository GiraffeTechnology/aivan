"""Versioned myAIVAN UI catalogs and fail-closed generated-catalog loading.

English is the sole source for FR/ES/DE/KO/JA generation.  The public API
serves only this fixed catalog or previously generated, atomically written
catalog files; callers cannot submit arbitrary source text for translation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "myaivan.ui-catalog.v1"
POLICY_VERSION = "dedicated-translator.qwen-proofread-only.v1"
GENERATED_LOCALES = ("fr", "es", "de", "ko", "ja")
MAX_MESSAGE_LENGTH = 2_048
MAX_CATALOG_LENGTH = 128_000
_SHA = re.compile(r"^[0-9a-f]{40}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# The keys are stable internal source handles used by the existing Chinese UI.
# Stable public message ids are derived only from these handles; English value
# changes therefore rotate catalog_version without silently changing identity.
AUTHORITATIVE_ENGLISH: dict[str, str] = {
    "myAIVAN 工作台": "myAIVAN Workbench",
    "登录 myAIVAN": "Sign in to myAIVAN",
    "安全登录": "Secure sign in",
    "访问凭据仅用于换取 HttpOnly 会话，不会保存在浏览器存储中。": "The access credential is exchanged only for an HttpOnly session and is never stored in browser storage.",
    "部署访问凭据": "Deployment access credential",
    "退出": "Sign out",
    "myAIVAN 首页": "myAIVAN home",
    "贸易业务工作台": "Trade operations workbench",
    "切换业务角色": "Switch business role",
    "主导航": "Main navigation",
    "当前角色": "Current role",
    "总览": "Overview",
    "业务案例": "Business cases",
    "录入询盘": "New inquiry",
    "人工转发": "Guided relay",
    "依赖健康": "Dependency health",
    "今日业务": "Today",
    "运营总览": "Operations overview",
    "录入新询盘": "Record inquiry",
    "最近更新": "Recent updates",
    "查看全部": "View all",
    "状态筛选": "Status filter",
    "全部状态": "All states",
    "刷新": "Refresh",
    "上一页": "Previous",
    "下一页": "Next",
    "← 返回案例": "← Back to cases",
    "录入买家询盘": "Record buyer inquiry",
    "买家标识": "Buyer ID",
    "买家名称": "Buyer name",
    "询盘原文": "Original inquiry",
    "客户或公司名称": "Customer or company name",
    "粘贴中文、英文或其他语言的原始询盘…": "Paste the original inquiry in Chinese, English, or another language…",
    "附件 / 语音": "Attachments / voice",
    "创建案例并生成待审批草稿": "Create case and draft for approval",
    "附件功能状态": "Attachment feature status",
    "当前候选仅提供元数据占位；对象存储授权与恶意内容扫描未完成前禁止上传。": "This candidate provides metadata placeholders only. Uploads remain disabled until object-storage authorization and malicious-content scanning are complete.",
    "微信 / 旺旺人工转发": "WeChat / WangWang guided relay",
    "发送后的回执编号": "Receipt reference after relay",
    "确认已人工转发": "Confirm manual relay",
    "AIVAN 只生成转发卡。必须由人员复制、在目标客户端发送并填写回执，系统不会自动外发个人 IM。": "AIVAN creates relay cards only. A person must copy, send in the destination client, and enter the receipt; the system never sends personal IM automatically.",
    "此页面只显示配置状态，不主动连接外部依赖，也不替代 CTYun、桥接、备份恢复和真机五轮验收证据。": "This page shows configuration status only. It does not connect to external dependencies or replace CTYun, bridge, backup-restore, and five-round device evidence.",
    "暂无数据": "No data",
    "当前筛选条件下没有可显示的记录。": "No records match the current filter.",
    "正在读取案例…": "Loading cases…",
    "询盘": "Inquiry",
    "寻源": "Sourcing",
    "等待供应商": "Awaiting supplier",
    "供应商已回复": "Supplier replied",
    "等待审批": "Awaiting approval",
    "已审批": "Approved",
    "质检": "Quality control",
    "物流": "Logistics",
    "完成": "Completed",
    "管理员": "Administrator",
    "销售": "Sales",
    "采购": "Procurement",
    "跟单": "Follow-up",
    "审批人": "Approver",
    "审计员": "Auditor",
    "买家": "Buyer",
    "供应商": "Supplier",
    "复制": "Copy",
    "审批": "Approve",
    "影响预览": "Impact preview",
    "纠错": "Correct",
    "导出审计": "Export audit",
    "已完成": "Completed",
    "已取消": "Cancelled",
    "无法恢复会话，请重新登录。": "The session could not be restored. Please sign in again.",
    "登录失败": "Sign-in failed",
    "已切换为": "Switched to ",
    "角色切换失败：": "Role switch failed: ",
    "冻结候选": "Frozen candidate",
    "候选未冻结": "Candidate not frozen",
    "仅可作为非生产工作台使用。": "This workbench is for non-production use only.",
    "未命名询盘": "Unnamed inquiry",
    "未知客户": "Unknown customer",
    "读取案例失败：": "Could not load cases: ",
    "可见案例": "Visible cases",
    "当前角色投影": "Current role projection",
    "活跃案例": "Active cases",
    "本页统计": "Current page",
    "需要人工决定": "Human decision required",
    "服务器授权": "Server authorization",
    "正在读取共享 Core 数据…": "Loading shared Core data…",
    "需求事实": "Requirement facts",
    "参与者与角色": "Participants and roles",
    "待办与草稿": "Tasks and drafts",
    "消息证据（仅摘要）": "Message evidence (digest only)",
    "回执": "Receipts",
    "事件时间线": "Event timeline",
    "审计记录": "Audit records",
    "待审批": "Pending approval",
    "摘要回执": "Receipt digest",
    "案例": "Case",
    "已创建": "created",
    "已进入 Core 工作流": "Entered the Core workflow",
    "询盘已写入共享 Core": "Inquiry recorded in shared Core",
    "创建失败：": "Creation failed: ",
    "已审批，等待人工转发": "Approved; awaiting manual relay",
    "已审批并产生发送回执": "Approved with a send receipt",
    "审批完成": "Approval complete",
    "审批失败：": "Approval failed: ",
    "影响范围：": "Impact scope: ",
    "预览失败：": "Preview failed: ",
    "请输入纠错原因。操作将写入不可变审计记录；不物理删除历史。": "Enter a correction reason. The operation writes an immutable audit record and does not physically delete history.",
    "纠错已应用": "Correction applied",
    "已创建补偿任务": "Compensation task created",
    "纠错失败：": "Correction failed: ",
    "正在读取转发队列…": "Loading relay queue…",
    "复制内容": "Copy content",
    "外部消息 ID 或人工回执编号": "External message ID or manual receipt reference",
    "读取转发队列失败：": "Could not load the relay queue: ",
    "已记录 relayed 回执": "Relayed receipt recorded",
    "确认失败：": "Confirmation failed: ",
    "数据库": "Database",
    "运行时配置": "Runtime configuration",
    "只读配置检查": "Read-only configuration check",
    "本地模型": "Local model",
    "候选版本": "Candidate version",
    "未冻结": "Not frozen",
    "已配置": "Configured",
    "待完成": "Pending",
    "读取健康状态失败：": "Could not load health status: ",
    "已复制到剪贴板": "Copied to clipboard",
    "正在加载翻译…": "Loading translation…",
    "翻译暂不可用，正在显示权威英文。": "Translation is unavailable; authoritative English is shown.",
}


def message_id(source_handle: str) -> str:
    digest = hashlib.sha256(source_handle.encode("utf-8")).hexdigest()[:20]
    return f"ui.{digest}"


def canonical_messages() -> dict[str, str]:
    return {message_id(source): text for source, text in AUTHORITATIVE_ENGLISH.items()}


def source_map() -> dict[str, str]:
    return {source: message_id(source) for source in AUTHORITATIVE_ENGLISH}


def catalog_version() -> str:
    encoded = json.dumps(
        canonical_messages(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_payload(candidate_sha: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "locale": "en",
        "source_locale": "en",
        "catalog_version": catalog_version(),
        "candidate_sha": candidate_sha or os.environ.get("AIVAN_CANDIDATE_SHA", "").strip(),
        "policy_version": POLICY_VERSION,
        "messages": canonical_messages(),
        "source_map": source_map(),
    }


def catalog_directory() -> Path | None:
    value = os.environ.get("AIVAN_UI_CATALOG_DIR", "").strip()
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        return None
    if os.name != "nt":
        mode = path.stat().st_mode
        if mode & 0o022:
            return None
    return path


def validate_catalog_directory(path: Path, *, create: bool = False) -> Path:
    """Return an absolute, private, non-symlink catalog directory."""

    if not path.is_absolute():
        raise ValueError("catalog directory must be absolute")
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("catalog directory is unavailable")
    if os.name != "nt" and path.stat().st_mode & 0o022:
        raise ValueError("catalog directory permissions are unsafe")
    return path


def _valid_text(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= MAX_MESSAGE_LENGTH
        and not _CONTROL.search(value)
    )


def validate_generated_catalog(
    payload: Any,
    *,
    locale: str,
    candidate_sha: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("catalog payload must be an object")
    if locale not in GENERATED_LOCALES or payload.get("locale") != locale:
        raise ValueError("catalog locale mismatch")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("catalog schema mismatch")
    if payload.get("source_locale") != "en":
        raise ValueError("catalog source must be English")
    if payload.get("catalog_version") != catalog_version():
        raise ValueError("catalog version is stale")
    if payload.get("candidate_sha") != candidate_sha or not _SHA.fullmatch(candidate_sha):
        raise ValueError("catalog candidate mismatch")
    if payload.get("policy_version") != POLICY_VERSION:
        raise ValueError("catalog policy mismatch")

    provider = str(payload.get("provider") or "").strip().lower()
    model = str(payload.get("model") or "").strip()
    backend = str(payload.get("backend") or "").strip()
    if provider in {"", "mock", "qwen", "ollama"} or "qwen" in provider:
        raise ValueError("catalog provider is not trusted")
    if not model or not backend or "qwen" in model.lower():
        raise ValueError("catalog generator identity is incomplete")

    proofreader = payload.get("proofreader")
    if proofreader is not None:
        if not isinstance(proofreader, dict):
            raise ValueError("catalog proofreader is invalid")
        if str(proofreader.get("role") or "").strip().lower() != "proofread-only":
            raise ValueError("catalog proofreader role is invalid")
        if str(proofreader.get("model") or "").strip() != "qwen3.5:9b":
            raise ValueError("catalog proofreader model is invalid")

    messages = payload.get("messages")
    expected = canonical_messages()
    if not isinstance(messages, dict) or set(messages) != set(expected):
        raise ValueError("catalog message set is incomplete")
    if not all(_valid_text(value) for value in messages.values()):
        raise ValueError("catalog contains invalid text")
    if sum(len(value) for value in messages.values()) > MAX_CATALOG_LENGTH:
        raise ValueError("catalog exceeds the size limit")
    provenance = payload.get("message_provenance")
    if not isinstance(provenance, dict) or set(provenance) != set(expected):
        raise ValueError("catalog message provenance is incomplete")
    provenance_proofreaders: list[dict[str, Any] | None] = []
    for item in provenance.values():
        if not isinstance(item, dict):
            raise ValueError("catalog message provenance is invalid")
        item_provider = str(item.get("provider") or "").strip().lower()
        item_model = str(item.get("model") or "").strip()
        item_backend = str(item.get("backend") or "").strip()
        if (
            item_provider != provider
            or item_model != model
            or item_backend != backend
            or item_provider in {"mock", "qwen", "ollama"}
            or "qwen" in item_provider
            or "qwen" in item_model.lower()
        ):
            raise ValueError("catalog message generator identity is invalid")
        item_proofreader = item.get("proofreader")
        provenance_proofreaders.append(item_proofreader)
        if item_proofreader is not None:
            if not isinstance(item_proofreader, dict):
                raise ValueError("catalog message proofreader is invalid")
            role = str(item_proofreader.get("role") or "").strip().lower()
            proof_model = str(item_proofreader.get("model") or "").strip()
            status_value = str(item_proofreader.get("status") or "").strip().lower()
            if role != "proofread-only" or proof_model != "qwen3.5:9b":
                raise ValueError("catalog message proofreader boundary is invalid")
            if status_value not in {"accepted", "revised", "not-required", "unavailable"}:
                raise ValueError("catalog message proofreader status is invalid")
    has_per_message_proofreader = [item is not None for item in provenance_proofreaders]
    if proofreader is None and any(has_per_message_proofreader):
        raise ValueError("catalog proofreader summary is missing")
    if proofreader is not None and not all(has_per_message_proofreader):
        raise ValueError("catalog proofreader provenance is inconsistent")
    if proofreader is not None:
        statuses = proofreader.get("statuses")
        observed = sorted(
            {str(item.get("status") or "").strip().lower() for item in provenance_proofreaders if item}
        )
        if not isinstance(statuses, list) or sorted(statuses) != observed:
            raise ValueError("catalog proofreader status summary is inconsistent")
    return payload


def load_generated_catalog(
    locale: str,
    *,
    candidate_sha: str | None = None,
    directory: Path | None = None,
) -> dict[str, Any]:
    candidate = candidate_sha or os.environ.get("AIVAN_CANDIDATE_SHA", "").strip()
    root = directory or catalog_directory()
    if root is None:
        raise ValueError("catalog directory is not configured")
    root = validate_catalog_directory(root)
    path = root / f"{locale}.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("catalog file is unavailable")
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode) or (
                os.name != "nt" and file_stat.st_mode & 0o022
            ):
                raise ValueError("catalog file permissions are unsafe")
            if file_stat.st_size > 1_048_576:
                raise ValueError("catalog file exceeds the size limit")
            with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                descriptor = -1
                payload = json.load(handle)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("catalog file is invalid") from exc
    return validate_generated_catalog(payload, locale=locale, candidate_sha=candidate)


def ready_locales(candidate_sha: str | None = None) -> list[str]:
    ready: list[str] = []
    for locale in GENERATED_LOCALES:
        try:
            load_generated_catalog(locale, candidate_sha=candidate_sha)
        except ValueError:
            continue
        ready.append(locale)
    return ready


def catalog_etag(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return f'"{digest}"'
