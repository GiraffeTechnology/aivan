"""Tests for aiven.platforms.domain_utils."""
import pytest
from aiven.platforms.domain_utils import normalize_domain, is_domain_allowed, detect_typosquatting
from aiven.platforms.models import TrustedPlatform


def _make_platform(domain_patterns: list[str]) -> TrustedPlatform:
    return TrustedPlatform(
        platform_id="test_platform",
        display_name="Test Platform",
        domain_patterns=domain_patterns,
    )


# --- normalize_domain ---

def test_normalize_domain_strips_https():
    assert normalize_domain("https://alibaba.com/product/123") == "alibaba.com"


def test_normalize_domain_strips_http():
    assert normalize_domain("http://alibaba.com") == "alibaba.com"


def test_normalize_domain_strips_www():
    assert normalize_domain("https://www.alibaba.com/products") == "alibaba.com"


def test_normalize_domain_plain_domain():
    assert normalize_domain("alibaba.com") == "alibaba.com"


def test_normalize_domain_empty_string():
    assert normalize_domain("") == ""


def test_normalize_domain_strips_query():
    assert normalize_domain("https://alibaba.com?ref=test") == "alibaba.com"


def test_normalize_domain_lowercases():
    assert normalize_domain("Alibaba.COM") == "alibaba.com"


# --- is_domain_allowed ---

def test_is_domain_allowed_exact_match():
    platform = _make_platform(["alibaba.com"])
    assert is_domain_allowed("alibaba.com", platform) is True


def test_is_domain_allowed_url_input():
    platform = _make_platform(["alibaba.com"])
    assert is_domain_allowed("https://alibaba.com/product/123", platform) is True


def test_is_domain_allowed_subdomain():
    platform = _make_platform(["alibaba.com"])
    assert is_domain_allowed("detail.alibaba.com", platform) is True


def test_is_domain_allowed_unrelated_domain_false():
    platform = _make_platform(["alibaba.com"])
    assert is_domain_allowed("evil.com", platform) is False


def test_is_domain_allowed_empty_domain():
    platform = _make_platform(["alibaba.com"])
    assert is_domain_allowed("", platform) is False


# --- detect_typosquatting ---

def test_detect_typosquatting_catches_embed():
    """alibaba.com.fake-shop.com contains 'alibaba.com' → flagged."""
    suspects = detect_typosquatting("alibaba.com.fake-shop.com", ["alibaba.com"])
    assert len(suspects) > 0


def test_detect_typosquatting_real_domain_not_flagged():
    suspects = detect_typosquatting("alibaba.com", ["alibaba.com"])
    assert len(suspects) == 0


def test_detect_typosquatting_subdomain_not_flagged():
    """Legitimate subdomain should NOT be flagged."""
    suspects = detect_typosquatting("detail.alibaba.com", ["alibaba.com"])
    assert len(suspects) == 0


def test_detect_typosquatting_returns_list():
    suspects = detect_typosquatting("evil-ali.com", ["alibaba.com"])
    assert isinstance(suspects, list)


def test_detect_typosquatting_multiple_trusted_domains():
    suspects = detect_typosquatting("alibaba.com.scam.net", ["alibaba.com", "aliexpress.com"])
    assert "alibaba.com" in suspects
