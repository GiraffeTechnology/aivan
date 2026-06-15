"""Tests for aiven.sourcing.supplier_registry."""
import pytest
from aivan.sourcing.supplier_registry import (
    register_supplier,
    get_supplier,
    list_suppliers,
    list_active,
    count,
    clear_registry,
)
from aivan.sourcing.supplier_models import SupplierProfile


@pytest.fixture(autouse=True)
def clean_registry():
    """Clear the in-memory registry before and after each test."""
    clear_registry()
    yield
    clear_registry()


def _make_supplier(supplier_id: str, name: str, active: bool = True) -> SupplierProfile:
    return SupplierProfile(
        supplier_id=supplier_id,
        name=name,
        categories=["apparel"],
        active=active,
    )


def test_registry_starts_empty():
    assert count() == 0


def test_register_and_retrieve():
    s = _make_supplier("sup_001", "Fabric Factory Co.")
    register_supplier(s)
    fetched = get_supplier("sup_001")
    assert fetched is not None
    assert fetched.name == "Fabric Factory Co."


def test_get_nonexistent_returns_none():
    assert get_supplier("nonexistent_xyz") is None


def test_list_suppliers_returns_list():
    register_supplier(_make_supplier("sup_001", "Factory A"))
    register_supplier(_make_supplier("sup_002", "Factory B"))
    suppliers = list_suppliers()
    assert isinstance(suppliers, list)
    assert len(suppliers) == 2


def test_list_active_excludes_inactive():
    register_supplier(_make_supplier("sup_001", "Active Factory", active=True))
    register_supplier(_make_supplier("sup_002", "Inactive Factory", active=False))
    active = list_active()
    assert len(active) == 1
    assert active[0].supplier_id == "sup_001"


def test_count_increases_on_register():
    assert count() == 0
    register_supplier(_make_supplier("sup_001", "A"))
    assert count() == 1
    register_supplier(_make_supplier("sup_002", "B"))
    assert count() == 2


def test_clear_registry():
    register_supplier(_make_supplier("sup_001", "A"))
    clear_registry()
    assert count() == 0


def test_register_overwrites_existing():
    s1 = _make_supplier("sup_001", "Old Name")
    s2 = SupplierProfile(supplier_id="sup_001", name="New Name", categories=["electronics"])
    register_supplier(s1)
    register_supplier(s2)
    fetched = get_supplier("sup_001")
    assert fetched.name == "New Name"
    assert count() == 1


def test_supplier_profile_fields_preserved():
    s = SupplierProfile(
        supplier_id="sup_full",
        name="Full Profile Supplier",
        categories=["apparel", "textiles"],
        region="Guangdong",
        country="China",
        moq_min=1000,
        moq_max=100000,
        daily_capacity=2000,
        quality_score=0.85,
        active=True,
    )
    register_supplier(s)
    fetched = get_supplier("sup_full")
    assert fetched.categories == ["apparel", "textiles"]
    assert fetched.region == "Guangdong"
    assert fetched.daily_capacity == 2000
    assert fetched.quality_score == 0.85
