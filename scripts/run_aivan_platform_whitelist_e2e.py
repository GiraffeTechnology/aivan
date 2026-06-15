#!/usr/bin/env python3
"""AIVAN Platform Whitelist E2E

Verifies:
  1. Built-in platforms (alibaba, aliexpress) are present
  2. is_domain_allowed() approves exact and subdomain matches
  3. is_domain_allowed() rejects typosquatting / fake-shop URLs
  4. normalize_domain() strips scheme, www, path, and query string
  5. detect_typosquatting() catches suspicious look-alike domains
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from aiven.platforms.whitelist import BUILT_IN_PLATFORMS
from aiven.platforms.domain_utils import (
    is_domain_allowed,
    normalize_domain,
    detect_typosquatting,
)


def _check(label: str, result, expected):
    status = "PASS" if result == expected else "FAIL"
    marker = "  [OK]" if result == expected else "  [!!]"
    print(f"{marker} {label}")
    print(f"       expected={expected!r}  got={result!r}")
    if result != expected:
        raise AssertionError(f"FAIL — {label}: expected {expected!r}, got {result!r}")


def main():
    print("=" * 60)
    print("AIVAN PLATFORM WHITELIST E2E")
    print("=" * 60)

    alibaba_platform = BUILT_IN_PLATFORMS["alibaba"]
    aliexpress_platform = BUILT_IN_PLATFORMS["aliexpress"]

    # ------------------------------------------------------------------
    # 1. Built-in platform presence
    # ------------------------------------------------------------------
    print("\n[1] Built-in platform registry")
    assert "alibaba" in BUILT_IN_PLATFORMS, "FAIL: 'alibaba' missing from BUILT_IN_PLATFORMS"
    assert "aliexpress" in BUILT_IN_PLATFORMS, "FAIL: 'aliexpress' missing from BUILT_IN_PLATFORMS"
    print(f"  [OK] alibaba  : {alibaba_platform.display_name}")
    print(f"  [OK] aliexpress: {aliexpress_platform.display_name}")
    assert alibaba_platform.built_in is True, "FAIL: alibaba.built_in should be True"
    assert aliexpress_platform.built_in is True, "FAIL: aliexpress.built_in should be True"
    print("  [1] OK")

    # ------------------------------------------------------------------
    # 2. normalize_domain
    # ------------------------------------------------------------------
    print("\n[2] normalize_domain()")
    cases_norm = [
        ("https://www.alibaba.com/product/123?utm=abc", "alibaba.com"),
        ("http://alibaba.com", "alibaba.com"),
        ("www.aliexpress.com", "aliexpress.com"),
        ("alibaba.com", "alibaba.com"),
        ("HTTPS://WWW.1688.COM/offer/123.html", "1688.com"),
    ]
    for url, expected in cases_norm:
        _check(f"normalize_domain({url!r})", normalize_domain(url), expected)
    print("  [2] OK")

    # ------------------------------------------------------------------
    # 3. is_domain_allowed — should return True
    # ------------------------------------------------------------------
    print("\n[3] is_domain_allowed() — expect True")
    allowed_cases = [
        ("alibaba.com", alibaba_platform),
        ("1688.com", alibaba_platform),
        ("https://www.alibaba.com/product/123", alibaba_platform),
        ("aliexpress.com", aliexpress_platform),
        ("https://www.aliexpress.com/item/abc.html", aliexpress_platform),
    ]
    for domain_or_url, platform in allowed_cases:
        _check(
            f"is_domain_allowed({domain_or_url!r}, {platform.platform_id})",
            is_domain_allowed(domain_or_url, platform),
            True,
        )
    print("  [3] OK")

    # ------------------------------------------------------------------
    # 4. is_domain_allowed — should return False (fake / typosquatting URLs)
    # ------------------------------------------------------------------
    print("\n[4] is_domain_allowed() — expect False (fake/typosquatted domains)")
    blocked_cases = [
        ("alibaba.com.fake-shop.com", alibaba_platform),
        ("alibaba.com.au", alibaba_platform),
        ("aliibaba.com", alibaba_platform),
        ("al1baba.com", alibaba_platform),
        ("aliexpress.com.scam.net", aliexpress_platform),
    ]
    for domain_or_url, platform in blocked_cases:
        _check(
            f"is_domain_allowed({domain_or_url!r}, {platform.platform_id})",
            is_domain_allowed(domain_or_url, platform),
            False,
        )
    print("  [4] OK")

    # ------------------------------------------------------------------
    # 5. detect_typosquatting
    # ------------------------------------------------------------------
    print("\n[5] detect_typosquatting()")
    trusted_domains = ["alibaba.com", "aliexpress.com", "1688.com"]

    # A genuine subdomain should NOT be flagged as typosquatting
    # (detect_typosquatting targets embedded look-alikes, not subdomains)
    suspects_clean = detect_typosquatting("alibaba.com", trusted_domains)
    print(f"  detect_typosquatting('alibaba.com')         → {suspects_clean}")

    # A fake-shop embedding "alibaba" should be flagged
    suspects_fake = detect_typosquatting("alibaba.com.fake-shop.com", trusted_domains)
    print(f"  detect_typosquatting('alibaba.com.fake-shop.com') → {suspects_fake}")
    assert "alibaba.com" in suspects_fake, (
        "FAIL: 'alibaba.com' should be in typosquatting suspects for 'alibaba.com.fake-shop.com'"
    )

    # A typo domain should be caught by Levenshtein
    suspects_typo = detect_typosquatting("aliibaba.com", trusted_domains)
    print(f"  detect_typosquatting('aliibaba.com')        → {suspects_typo}")
    assert len(suspects_typo) > 0, (
        "FAIL: 'aliibaba.com' should trigger typosquatting detection"
    )
    print("  [5] OK")

    # ------------------------------------------------------------------
    # Done
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("AIVAN PLATFORM WHITELIST E2E: PASS")
    print("=" * 60)


if __name__ == "__main__":
    main()
