from __future__ import annotations
import threading
from aiven.platforms.models import TrustedPlatform, PlatformSuggestion
from aiven.platforms.whitelist import get_built_in_platforms
from aiven.utils.time_utils import utcnow_iso
from aiven.utils.ids import new_suggestion_id

_platforms: dict[str, TrustedPlatform] = {}
_suggestions: dict[str, PlatformSuggestion] = {}
_lock = threading.Lock()
_initialized = False

def _ensure_init():
    global _initialized
    if not _initialized:
        with _lock:
            if not _initialized:
                for pid, p in get_built_in_platforms().items():
                    _platforms[pid] = p
                _initialized = True

def get_platform(platform_id: str) -> TrustedPlatform | None:
    _ensure_init()
    return _platforms.get(platform_id)

def list_all_platforms() -> list[TrustedPlatform]:
    _ensure_init()
    return list(_platforms.values())

def list_trusted_platforms() -> list[TrustedPlatform]:
    _ensure_init()
    return [p for p in _platforms.values() if p.status in ("built_in", "trusted")]

def is_platform_trusted(platform_id: str) -> bool:
    _ensure_init()
    p = _platforms.get(platform_id)
    return p is not None and p.status in ("built_in", "trusted")

def is_platform_blocked(platform_id: str) -> bool:
    _ensure_init()
    p = _platforms.get(platform_id)
    return p is not None and p.status == "blocked"

def add_platform(platform: TrustedPlatform) -> TrustedPlatform:
    _ensure_init()
    with _lock:
        if platform.platform_id in _platforms and _platforms[platform.platform_id].built_in:
            return _platforms[platform.platform_id]
        _platforms[platform.platform_id] = platform
    return platform

def update_platform_status(platform_id: str, status: str) -> TrustedPlatform | None:
    _ensure_init()
    with _lock:
        p = _platforms.get(platform_id)
        if p and not p.built_in:
            p.status = status
            p.updated_at = utcnow_iso()
            if status in ("trusted",):
                p.user_confirmed = True
    return p

def suggest_platform(domain: str, reason: str, display_name: str = "") -> PlatformSuggestion:
    _ensure_init()
    platform_id = f"suggested_{domain.replace('.', '_')}"
    sug = PlatformSuggestion(
        suggestion_id=new_suggestion_id(),
        platform_id=platform_id,
        display_name=display_name or domain,
        domain=domain,
        reason=reason,
        status="pending_review",
        created_at=utcnow_iso(),
    )
    with _lock:
        _suggestions[sug.suggestion_id] = sug
        if platform_id not in _platforms:
            from aiven.platforms.models import TrustedPlatform
            _platforms[platform_id] = TrustedPlatform(
                platform_id=platform_id,
                display_name=display_name or domain,
                status="pending_review",
                domain_patterns=[domain],
                created_at=utcnow_iso(),
                updated_at=utcnow_iso(),
            )
    return sug

def list_suggestions() -> list[PlatformSuggestion]:
    _ensure_init()
    return list(_suggestions.values())

def approve_suggestion(suggestion_id: str) -> PlatformSuggestion | None:
    _ensure_init()
    sug = _suggestions.get(suggestion_id)
    if sug:
        sug.status = "approved"
        update_platform_status(sug.platform_id, "trusted")
    return sug

def reject_suggestion(suggestion_id: str) -> PlatformSuggestion | None:
    _ensure_init()
    sug = _suggestions.get(suggestion_id)
    if sug:
        sug.status = "rejected"
        update_platform_status(sug.platform_id, "rejected")
    return sug

def block_suggestion(suggestion_id: str) -> PlatformSuggestion | None:
    _ensure_init()
    sug = _suggestions.get(suggestion_id)
    if sug:
        sug.status = "blocked"
        update_platform_status(sug.platform_id, "blocked")
    return sug

def reset_registry():
    global _initialized
    with _lock:
        _platforms.clear()
        _suggestions.clear()
        _initialized = False
