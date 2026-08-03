"""Regression tests for Stage 1-3 tenant-scoped repositories and registries."""

from aivan.db.repositories.account_repo import AccountRepository
from aivan.db.repositories.event_repo import ExecutionEventRepository
from aivan.db.repositories.preference_repo import UserPreferenceRepository
from aivan.db.repositories.platform_repo import PlatformRepository
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.db.repositories.supplier_repo import SupplierRepository
from aivan.sourcing.supplier_models import SupplierProfile
from aivan.sourcing.supplier_registry import clear_registry, get_supplier, list_active, register_supplier
from aivan.platforms.models import TrustedPlatform
from aivan.platforms.platform_registry import add_platform, get_platform, reset_registry


def test_account_preference_and_supplier_queries_never_cross_tenants(db_session):
    accounts = AccountRepository(db_session)
    accounts.upsert("account-a", {"platform": "wechat"}, tenant_id="tenant-a")
    accounts.upsert("account-b", {"platform": "wechat"}, tenant_id="tenant-b")
    assert accounts.get("account-a", tenant_id="tenant-b") is None
    assert [item.account_connection_id for item in accounts.list_active(tenant_id="tenant-a")] == ["account-a"]
    accounts.upsert("shared-account", {"platform": "wechat"}, tenant_id="tenant-a")
    accounts.upsert("shared-account", {"platform": "wechat"}, tenant_id="tenant-b")
    assert accounts.get("shared-account", tenant_id="tenant-a").storage_key != accounts.get("shared-account", tenant_id="tenant-b").storage_key

    preferences = UserPreferenceRepository(db_session)
    preferences.upsert("user-a", "strategy", {"speed": True}, tenant_id="tenant-a")
    preferences.upsert("user-b", "strategy", {"price": True}, tenant_id="tenant-b")
    assert preferences.list_for_user("user-a", tenant_id="tenant-b") == []
    assert [item.user_id for item in preferences.list_all(tenant_id="tenant-a")] == ["user-a"]

    suppliers = SupplierRepository(db_session)
    suppliers.upsert("supplier-a", {"name": "A"}, tenant_id="tenant-a")
    suppliers.upsert("supplier-b", {"name": "B"}, tenant_id="tenant-b")
    assert suppliers.get("supplier-a", tenant_id="tenant-b") is None
    assert [item.supplier_id for item in suppliers.list_active(tenant_id="tenant-a")] == ["supplier-a"]
    suppliers.upsert("shared-supplier", {"name": "Tenant A shared"}, tenant_id="tenant-a")
    suppliers.upsert("shared-supplier", {"name": "Tenant B shared"}, tenant_id="tenant-b")
    assert suppliers.get("shared-supplier", tenant_id="tenant-a").storage_key != suppliers.get("shared-supplier", tenant_id="tenant-b").storage_key

    platforms = PlatformRepository(db_session)
    platforms.upsert("shared-platform", {"display_name": "A"}, tenant_id="tenant-a")
    platforms.upsert("shared-platform", {"display_name": "B"}, tenant_id="tenant-b")
    assert platforms.get("shared-platform", tenant_id="tenant-a").storage_key != platforms.get("shared-platform", tenant_id="tenant-b").storage_key


def test_in_memory_supplier_registry_is_tenant_scoped():
    clear_registry()
    try:
        register_supplier(SupplierProfile(supplier_id="shared", name="Tenant A"), tenant_id="tenant-a")
        register_supplier(SupplierProfile(supplier_id="shared", name="Tenant B"), tenant_id="tenant-b")
        assert get_supplier("shared", tenant_id="tenant-a").name == "Tenant A"
        assert get_supplier("shared", tenant_id="tenant-b").name == "Tenant B"
        assert [item.name for item in list_active(tenant_id="tenant-a")] == ["Tenant A"]
    finally:
        clear_registry()


def test_execution_event_infers_project_tenant_and_filters_reads(db_session):
    project = ProjectRepository(db_session).create(
        "conversation-a", "buyer-a", tenant_id="tenant-a"
    )
    assert project.tenant_id == "tenant-a"
    events = ExecutionEventRepository(db_session)
    record = events.append(project.project_id, "TEST", "tenant inference")
    assert record.tenant_id == "tenant-a"
    assert len(events.list_for_project(project.project_id, tenant_id="tenant-a")) == 1
    assert events.list_for_project(project.project_id, tenant_id="tenant-b") == []


def test_custom_platform_whitelist_is_tenant_scoped():
    reset_registry()
    try:
        add_platform(
            TrustedPlatform(platform_id="tenant-market", display_name="Tenant Market", status="trusted"),
            tenant_id="tenant-a",
        )
        assert get_platform("tenant-market", tenant_id="tenant-a") is not None
        assert get_platform("tenant-market", tenant_id="tenant-b") is None
        # Built-in policy remains visible to every tenant, but cannot be overwritten.
        assert get_platform("alibaba", tenant_id="tenant-b") is not None
    finally:
        reset_registry()

