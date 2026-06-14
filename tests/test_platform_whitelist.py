"""Tests for aiven.platforms.whitelist — built-in platform entries."""
import pytest
from aiven.platforms.whitelist import get_built_in_platforms, is_built_in, BUILT_IN_PLATFORMS


def test_alibaba_is_built_in():
    assert is_built_in("alibaba") is True


def test_aliexpress_is_built_in():
    assert is_built_in("aliexpress") is True


def test_unknown_platform_not_built_in():
    assert is_built_in("some_random_platform_xyz") is False


def test_get_built_in_platforms_returns_dict():
    platforms = get_built_in_platforms()
    assert isinstance(platforms, dict)


def test_get_built_in_platforms_contains_alibaba():
    platforms = get_built_in_platforms()
    assert "alibaba" in platforms


def test_get_built_in_platforms_contains_aliexpress():
    platforms = get_built_in_platforms()
    assert "aliexpress" in platforms


def test_alibaba_domain_patterns():
    platforms = get_built_in_platforms()
    alibaba = platforms["alibaba"]
    assert "alibaba.com" in alibaba.domain_patterns
    assert "1688.com" in alibaba.domain_patterns


def test_aliexpress_domain_patterns():
    platforms = get_built_in_platforms()
    aliexpress = platforms["aliexpress"]
    assert "aliexpress.com" in aliexpress.domain_patterns


def test_alibaba_is_trusted_status():
    platforms = get_built_in_platforms()
    alibaba = platforms["alibaba"]
    assert alibaba.status == "built_in"


def test_alibaba_user_confirmed():
    platforms = get_built_in_platforms()
    alibaba = platforms["alibaba"]
    assert alibaba.user_confirmed is True


def test_get_built_in_platforms_returns_new_copy():
    """Mutating the returned dict should not affect the original."""
    p1 = get_built_in_platforms()
    p1["injected"] = None
    p2 = get_built_in_platforms()
    assert "injected" not in p2
