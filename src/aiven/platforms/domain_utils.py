import re
import urllib.parse

def normalize_domain(url_or_domain: str) -> str:
    """Extract and normalize domain from URL or domain string."""
    if not url_or_domain:
        return ""
    s = url_or_domain.strip().lower()
    if s.startswith("http://") or s.startswith("https://"):
        try:
            parsed = urllib.parse.urlparse(s)
            s = parsed.netloc or parsed.path
        except Exception:
            pass
    s = s.split("/")[0].split("?")[0].split("#")[0]
    if s.startswith("www."):
        s = s[4:]
    return s

def is_domain_allowed(domain: str, platform) -> bool:
    """Check if a domain matches any of the platform's allowed domain patterns."""
    domain = normalize_domain(domain)
    if not domain:
        return False
    for pattern in platform.domain_patterns:
        norm_pattern = normalize_domain(pattern)
        if domain == norm_pattern:
            return True
        if domain.endswith("." + norm_pattern):
            return True
    return False

def detect_typosquatting(domain: str, trusted_domains: list[str]) -> list[str]:
    """Return list of trusted domains that the given domain may be squatting on."""
    domain = normalize_domain(domain)
    suspects = []
    for trusted in trusted_domains:
        trusted_norm = normalize_domain(trusted)
        if trusted_norm in domain and domain != trusted_norm and not domain.endswith("." + trusted_norm):
            suspects.append(trusted)
        if _levenshtein(domain.split(".")[0], trusted_norm.split(".")[0]) <= 2 and domain != trusted_norm:
            suspects.append(trusted)
    return list(set(suspects))

def detect_punycode_or_homograph(domain: str) -> bool:
    """Return True if domain uses punycode or homograph characters."""
    if "xn--" in domain.lower():
        return True
    for ch in domain:
        if ord(ch) > 127:
            return True
    return False

def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        return _levenshtein(b, a)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (0 if ca == cb else 1)))
        prev = curr
    return prev[len(b)]
