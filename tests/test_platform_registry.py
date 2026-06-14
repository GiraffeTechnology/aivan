"""Tests for aiven.platforms.platform_registry — PlatformRegistry."""
import pytest
from aiven.platforms.platform_registry import (
    get_platform,
    list_all_platforms,
    list_trusted_platforms,
    is_platform_trusted,
    is_platform_blocked,
    add_platform,
    reset_registry,
)
from aiven.platforms.models import TrustedPlatform
from aiven.utils.time_utils import utcnow_iso


@pytest.fixture(autouse=True)
def reset_between_tests():
    """Reset registry state before each test to avoid cross-test pollution."""
    reset_registry()
    yield
    reset_registry()


def test_alibaba_is_trusted():
    assert is_platform_trusted("alibaba") is True


def test_aliexpress_is_trusted():
    assert is_platform_trusted("aliexpress") is True


def test_unknown_platform_not_trusted():
    assert is_platform_trusted("totally_unknown_platform_xyz") is False


def test_get_alibaba_platform():
    platform = get_platform("alibaba")
    assert platform is not None
    assert platform.platform_id == "alibaba"


def test_get_aliexpress_platform():
    platform = get_platform("aliexpress")
    assert platform is not None
    assert platform.platform_id == "aliexpress"


def test_get_nonexistent_platform_returns_none():
    assert get_platform("nonexistent_xyz") is None


def test_list_all_platforms_includes_builtins():
    platforms = list_all_platforms()
    ids = [p.platform_id for p in platforms]
    assert "alibaba" in ids
    assert "aliexpress" in ids


def test_list_trusted_platforms_includes_alibaba():
    trusted = list_trusted_platforms()
    ids = [p.platform_id for p in trusted]
    assert "alibaba" in ids


def test_is_platform_blocked_false_for_builtins():
    assert is_platform_blocked("alibaba") is False


def test_add_custom_platform():
    custom = TrustedPlatform(
        platform_id="test_custom_platform",
        display_name="Custom Platform",
        status="trusted",
        domain_patterns=["custom-platform.com"],
        created_at=utcnow_iso(),
        updated_at=utcnow_iso(),
    )
    added = add_platform(custom)
    assert added.platform_id == "test_custom_platform"
    assert is_platform_trusted("test_custom_platform") is True


def test_builtin_cannot_be_overwritten():
    """add_platform() on a built-in should return the existing built-in."""
    replacement = TrustedPlatform(
        platform_id="alibaba",
        display_name="Fake Alibaba",
        status="blocked",
        created_at=utcnow_iso(),
        updated_at=utcnow_iso(),
    )
    result = add_platform(replacement)
    # Built-in should be returned unchanged (status stays built_in)
    assert result.status == "built_in"


def test_alibaba_built_in_flag():
    platform = get_platform("alibaba")
    assert platform.built_in is True
