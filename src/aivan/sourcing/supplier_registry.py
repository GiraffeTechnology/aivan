from __future__ import annotations
import threading
from aivan.sourcing.supplier_models import SupplierProfile

_registry: dict[tuple[str, str], SupplierProfile] = {}
_lock = threading.Lock()

def register_supplier(profile: SupplierProfile, *, tenant_id: str = "legacy") -> None:
    with _lock:
        _registry[(tenant_id, profile.supplier_id)] = profile

def get_supplier(supplier_id: str, *, tenant_id: str = "legacy") -> SupplierProfile | None:
    return _registry.get((tenant_id, supplier_id))

def list_suppliers(*, tenant_id: str = "legacy") -> list[SupplierProfile]:
    return [profile for (scope, _), profile in _registry.items() if scope == tenant_id]

def list_active(*, tenant_id: str = "legacy") -> list[SupplierProfile]:
    return [s for s in list_suppliers(tenant_id=tenant_id) if s.active]

def count(*, tenant_id: str = "legacy") -> int:
    return len(list_suppliers(tenant_id=tenant_id))

def clear_registry(*, tenant_id: str | None = None) -> None:
    with _lock:
        if tenant_id is None:
            _registry.clear()
        else:
            for key in [key for key in _registry if key[0] == tenant_id]:
                _registry.pop(key, None)

def load_from_db(db_session, *, tenant_id: str | None = "legacy") -> int:
    from aivan.db.repositories.supplier_repo import SupplierRepository
    repo = SupplierRepository(db_session)
    records = (
        repo.list_active_all_tenants()
        if tenant_id is None
        else repo.list_active(tenant_id=tenant_id)
    )
    loaded = 0
    for r in records:
        profile = SupplierProfile(
            supplier_id=r.supplier_id or r.storage_key,
            name=r.name,
            company_type=r.company_type or "",
            categories=r.categories_json or [],
            capabilities=r.capabilities_json or [],
            materials=r.materials_json or [],
            moq_min=r.moq_min or 0,
            moq_max=r.moq_max or 0,
            daily_capacity=r.daily_capacity or 0,
            monthly_capacity=r.monthly_capacity or 0,
            region=r.region or "",
            country=r.country or "",
            languages=r.languages_json or [],
            channels=r.channels_json or [],
            email=r.email or "",
            openclaw_peer_id=r.openclaw_peer_id or "",
            payment_terms=r.payment_terms or "",
            incoterms_supported=r.incoterms_json or [],
            logistics_modes=r.logistics_modes_json or [],
            quality_score=r.quality_score or 0.0,
            delivery_score=r.delivery_score or 0.0,
            price_score=r.price_score or 0.0,
            past_performance_score=r.past_performance_score or 0.0,
            risk_tags=r.risk_tags_json or [],
            notes=r.notes or "",
            active=r.active,
        )
        register_supplier(profile, tenant_id=r.tenant_id or "legacy")
        loaded += 1
    return loaded

