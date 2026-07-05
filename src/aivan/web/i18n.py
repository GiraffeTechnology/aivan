"""UI string catalogs for the myaivan Web UI.

English is the system/canonical language. ``en`` and ``zh`` catalogs are
built in; any other language is produced by translating the English catalog
through giraffe-language-skill (``POST /v1/outbound/render``), one string at a
time, cached in-process. Translation is fail-soft: strings the service cannot
translate stay English, and when the service is unavailable the whole catalog
falls back to English — the UI must never break because translation is down.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

# Canonical (system-language) UI strings. Keys are stable identifiers used by
# data-i18n attributes in templates and by t() lookups in myaivan.js.
CATALOG_EN: dict[str, str] = {
    "welcome.title": "Welcome back. What should your AIVAN handle today?",
    "welcome.tagline": (
        "myaivan is your AIVAN digital trade assistant for inquiry management, "
        "business communication, and human-confirmed outbound messages."
    ),
    "welcome.start": "Start Working",
    "work.brand_sub": "AIVAN digital trade assistant",
    "work.backup": "Backup",
    "work.backup_tooltip": "Backup Case",
    "work.review_title": "Outbound review",
    "work.review_empty": (
        "AIVAN-generated outbound drafts will appear here for your review. "
        "Every outbound message requires human confirmation."
    ),
    "work.paste": "Paste",
    "work.paste_tooltip": "Paste from clipboard",
    "work.upload_file": "Upload file",
    "work.upload_image": "Upload image",
    "work.voice": "Voice",
    "work.voice_tooltip": "Voice input coming soon",
    "work.send": "Send",
    "work.placeholder": "Paste a buyer inquiry, supplier reply, or tell AIVAN what to handle next...",
    "draft.copy": "Copy",
    "draft.copy_tooltip": "Copy for manual paste",
    "draft.email": "Email",
    "draft.email_tooltip": "Send by Email",
    "draft.mark_sent": "Sent",
    "draft.mark_sent_tooltip": "Mark as manually sent",
    "draft.reject": "Reject",
    "draft.reject_tooltip": "Reject draft",
    "draft.risk_label": "Risk",
    "email.modal_title": "Send by Email",
    "email.modal_real": "This will send a real email through aivan-openclaw. Please confirm the recipient and content.",
    "email.modal_mock": "Mock mode: no real email will be delivered.",
    "email.recipient": "Recipient",
    "email.confirm": "Confirm send",
    "email.cancel": "Cancel",
    "status.processing": "AIVAN is processing…",
    "status.send_failed": "Send failed",
    "status.pasted": "Clipboard content pasted into the input box.",
    "status.clipboard_empty": "Clipboard is empty.",
    "status.paste_fallback": "Please paste manually with Ctrl+V / Cmd+V.",
    "status.uploading": "Uploading…",
    "status.upload_failed": "Upload failed",
    "status.copied": "Copied — paste it into your IM tool (WeChat / WhatsApp / LINE / Wangwang), then click ✅.",
    "status.copy_blocked": "Clipboard blocked — select the draft text and copy manually.",
    "status.marked_sent": "Recorded as manually sent.",
    "status.rejected": "Draft rejected — tell AIVAN how to revise it.",
    "status.action_failed": "Action failed",
    "status.email_sending": "Sending email…",
    "status.email_sent": "Email sent via aivan-openclaw.",
    "status.email_mock": "Mock send recorded — no real email was delivered.",
    "status.email_failed": "Email failed",
    "status.email_not_configured": "Email sending is not configured. Please copy the draft manually.",
    "status.backup_done": "Backup exported.",
    "status.backup_failed": "Backup failed",
    "status.voice_soon": "Voice input coming soon.",
    "status.init_failed": "Initialization failed",
    "lang.tooltip": "Switch language",
}

# Built-in curated Chinese catalog (product copy from the PRD).
CATALOG_ZH: dict[str, str] = {
    "welcome.title": "欢迎回来。今天要让你的 AIVAN 处理哪一条询价？",
    "welcome.tagline": "myaivan 是你的 AIVAN 数字业务员，用于管理询价、处理贸易信息收发，并在所有外发商务信息前进行人工确认。",
    "welcome.start": "开始工作",
    "work.brand_sub": "AIVAN 数字业务员",
    "work.backup": "备份",
    "work.backup_tooltip": "备份当前案件",
    "work.review_title": "外发审核",
    "work.review_empty": "AIVAN 生成的外发草稿会出现在这里，所有外发商务信息均需人工确认。",
    "work.paste": "粘贴",
    "work.paste_tooltip": "从剪贴板粘贴",
    "work.upload_file": "上传文件",
    "work.upload_image": "上传图片",
    "work.voice": "语音",
    "work.voice_tooltip": "语音输入即将上线",
    "work.send": "发送",
    "work.placeholder": "粘贴客户询价、供应商回复，或告诉 AIVAN 下一步怎么处理……",
    "draft.copy": "复制",
    "draft.copy_tooltip": "复制，用于手动粘贴",
    "draft.email": "邮件",
    "draft.email_tooltip": "通过邮件外发",
    "draft.mark_sent": "已发送",
    "draft.mark_sent_tooltip": "已粘贴并发送",
    "draft.reject": "不通过",
    "draft.reject_tooltip": "审核不通过",
    "draft.risk_label": "风险提示",
    "email.modal_title": "通过邮件外发",
    "email.modal_real": "将通过 aivan-openclaw 真实外发邮件，请确认收件人与内容。",
    "email.modal_mock": "当前为 MOCK 演示模式：不会真正发出邮件。",
    "email.recipient": "收件人",
    "email.confirm": "确认外发",
    "email.cancel": "取消",
    "status.processing": "AIVAN 正在处理…",
    "status.send_failed": "发送失败",
    "status.pasted": "剪贴板内容已粘贴到输入框。",
    "status.clipboard_empty": "剪贴板为空。",
    "status.paste_fallback": "浏览器未允许读取剪贴板，请使用 Ctrl+V / Cmd+V 手动粘贴。",
    "status.uploading": "上传中…",
    "status.upload_failed": "上传失败",
    "status.copied": "已复制，请粘贴到微信 / WhatsApp / LINE / 旺旺后回来点 ✅。",
    "status.copy_blocked": "浏览器未允许写剪贴板，请手动选择草稿文本复制。",
    "status.marked_sent": "已记录为人工外发。",
    "status.rejected": "草稿已拒绝，请告诉 AIVAN 如何修改。",
    "status.action_failed": "操作失败",
    "status.email_sending": "正在外发邮件…",
    "status.email_sent": "邮件已通过 aivan-openclaw 外发。",
    "status.email_mock": "MOCK 模式外发成功（未真实发送）。",
    "status.email_failed": "邮件外发失败",
    "status.email_not_configured": "邮件外发尚未配置，请复制草稿后手动发送。",
    "status.backup_done": "备份已导出。",
    "status.backup_failed": "备份失败",
    "status.voice_soon": "语音输入即将上线。",
    "status.init_failed": "初始化失败",
    "lang.tooltip": "切换语言",
}

BUILTIN_CATALOGS: dict[str, dict[str, str]] = {"en": CATALOG_EN, "zh": CATALOG_ZH}

# Languages offered by the UI switcher. Anything beyond en/zh is translated
# on demand through giraffe-language-skill.
SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "zh": "中文",
    "ja": "日本語",
    "ko": "한국어",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
    "pt": "Português",
    "ru": "Русский",
    "ar": "العربية",
}

_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()


def normalize_lang(tag: str) -> str:
    """'zh-CN' → 'zh'; unknown/empty → 'en'."""
    primary = (tag or "").strip().lower().split("-")[0].split("_")[0]
    return primary if primary in SUPPORTED_LANGUAGES else "en"


def _translate_text(client, target_language: str, text: str) -> str | None:
    result = client.render_outbound(
        target_language=target_language,
        canonical_text=text,
        message_type="ui_string",
        tone="neutral",
    )
    if not result.ok or not isinstance(result.data, dict):
        return None
    data = result.data
    for key in ("rendered_text", "text", "output", "canonical_text"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def get_catalog(lang: str) -> dict:
    """Return {'lang', 'source', 'strings'} for the requested language.

    source: builtin | language_skill | language_skill_partial | fallback_en
    """
    lang = normalize_lang(lang)
    if lang in BUILTIN_CATALOGS:
        return {"lang": lang, "source": "builtin", "strings": dict(BUILTIN_CATALOGS[lang])}

    with _cache_lock:
        cached = _cache.get(lang)
    if cached is not None:
        return cached

    from aivan.integrations.language_skill_client import LanguageSkillClient, is_enabled

    strings = dict(CATALOG_EN)
    source = "fallback_en"
    if is_enabled():
        client = LanguageSkillClient()
        translated = 0
        for key, text in CATALOG_EN.items():
            try:
                rendered = _translate_text(client, lang, text)
            except Exception:
                rendered = None
            if rendered:
                strings[key] = rendered
                translated += 1
        if translated == len(CATALOG_EN):
            source = "language_skill"
        elif translated > 0:
            source = "language_skill_partial"
        else:
            logger.warning("language skill returned no translations for %s; serving English", lang)
    else:
        logger.info("language skill disabled; serving English catalog for %s", lang)

    catalog = {"lang": lang, "source": source, "strings": strings}
    # Cache only useful results — a full English fallback should be retried on
    # the next request in case the service comes back.
    if source != "fallback_en":
        with _cache_lock:
            _cache[lang] = catalog
    return catalog


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
