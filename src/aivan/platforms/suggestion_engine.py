from __future__ import annotations
from aivan.platforms.platform_registry import is_platform_trusted, is_platform_blocked, suggest_platform
from aivan.platforms.domain_utils import normalize_domain, detect_typosquatting, detect_punycode_or_homograph

TRUSTED_DOMAIN_POOL = ["alibaba.com", "1688.com", "aliexpress.com"]

def check_and_suggest_domain(domain: str, reason: str = "found in supplier discovery") -> dict:
    """Check if a domain is trusted. If not, create a suggestion and return status."""
    domain_norm = normalize_domain(domain)
    if not domain_norm:
        return {"action": "skip", "reason": "empty domain"}

    if detect_punycode_or_homograph(domain_norm):
        return {"action": "block", "reason": "punycode or homograph detected", "domain": domain_norm}

    squats = detect_typosquatting(domain_norm, TRUSTED_DOMAIN_POOL)
    if squats:
        return {"action": "block", "reason": f"possible typosquatting of {squats}", "domain": domain_norm}

    if is_platform_blocked(domain_norm):
        return {"action": "blocked", "reason": "platform is blocked", "domain": domain_norm}

    platform_id = f"suggested_{domain_norm.replace('.', '_')}"
    if is_platform_trusted(platform_id):
        return {"action": "allowed", "reason": "user-confirmed trusted platform", "domain": domain_norm}

    for tid in ["alibaba", "aliexpress"]:
        from aivan.platforms.platform_registry import get_platform
        p = get_platform(tid)
        if p:
            from aivan.platforms.domain_utils import is_domain_allowed
            if is_domain_allowed(domain_norm, p):
                return {"action": "allowed", "reason": f"matches built-in platform {tid}", "domain": domain_norm}

    sug = suggest_platform(domain_norm, reason)
    return {"action": "suggested", "suggestion_id": sug.suggestion_id, "reason": "non-whitelisted platform, suggestion created", "domain": domain_norm}
