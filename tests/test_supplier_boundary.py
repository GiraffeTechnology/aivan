"""Supplier stub gating boundary tests (PRD §10, §18.10)."""
from __future__ import annotations

from aivan.integrations import giraffe_db
from aivan.integrations.giraffe_db import GiraffeDBClient, stub_suppliers_allowed
from aivan.execution.safety import evaluate_supplier_readiness
from aivan.schemas.requirement import BuyerRequirement
from aivan.sourcing.supplier_registry import clear_registry


def _requirement() -> BuyerRequirement:
    return BuyerRequirement(category="apparel", product_type="shirt", quantity=5000)


def test_stub_suppliers_disabled_in_production(monkeypatch, db_session):
    monkeypatch.setenv("AIVAN_ENV", "production")
    clear_registry()
    assert stub_suppliers_allowed() is False
    context = GiraffeDBClient(db_session).build_context(_requirement())
    assert context.suppliers == []


def test_stub_suppliers_enabled_only_when_configured(monkeypatch, db_session):
    monkeypatch.setenv("AIVAN_ENV", "local")
    clear_registry()

    monkeypatch.setenv("AIVAN_ALLOW_STUB_SUPPLIERS", "true")
    assert stub_suppliers_allowed() is True
    context = GiraffeDBClient(db_session).build_context(_requirement())
    assert context.suppliers  # demo stubs present

    monkeypatch.setenv("AIVAN_ALLOW_STUB_SUPPLIERS", "false")
    context = GiraffeDBClient(db_session).build_context(_requirement())
    assert context.suppliers == []


def test_no_suppliers_returns_pending_supplier_selection():
    feasibility, ready = evaluate_supplier_readiness([])
    assert feasibility == "none"
    assert ready is False


def test_zero_suppliers_pending_selection():
    from aivan.execution.safety import supplier_action

    assert supplier_action([]) == "pending_supplier_selection"


def test_one_supplier_returns_pending_supplier_confirmation_not_error():
    from aivan.execution.safety import supplier_action

    action = supplier_action([{"supplier_id": "s1", "email": "a@x.com"}])
    assert action == "pending_supplier_confirmation"  # confirmation, never an error


def test_two_suppliers_allowed_with_thin_feasibility():
    feasibility, ready = evaluate_supplier_readiness(
        [{"supplier_id": "s1", "email": "a@x.com"}, {"supplier_id": "s2", "email": "b@x.com"}]
    )
    assert feasibility == "thin"
    assert ready is True


def test_less_than_three_suppliers_does_not_error():
    one = evaluate_supplier_readiness([{"supplier_id": "s1", "email": "a@x.com"}])
    two = evaluate_supplier_readiness(
        [{"supplier_id": "s1", "email": "a@x.com"}, {"supplier_id": "s2", "email": "b@x.com"}]
    )
    three = evaluate_supplier_readiness(
        [
            {"supplier_id": "s1", "email": "a@x.com"},
            {"supplier_id": "s2", "email": "b@x.com"},
            {"supplier_id": "s3", "email": "c@x.com"},
        ]
    )
    assert one[0] == "single"
    assert two == ("thin", True)
    assert three == ("sufficient", True)
