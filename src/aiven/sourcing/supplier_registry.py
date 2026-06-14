from __future__ import annotations
import threading
from aiven.sourcing.supplier_models import SupplierProfile

_registry: dict[str, SupplierProfile] = {}
_lock = threading.Lock()

def register_supplier(profile: SupplierProfile) -> None:
    with _lock:
        _registry[profile.supplier_id] = profile

def get_supplier(supplier_id: str) -> SupplierProfile | None:
    return _registry.get(supplier_id)

def list_suppliers() -> list[SupplierProfile]:
    return list(_registry.values())

def list_active() -> list[SupplierProfile]:
    return [s for s in _registry.values() if s.active]

def count() -> int:
    return len(_registry)

def clear_registry() -> None:
    with _lock:
        _registry.clear()

def load_from_db(db_session) -> int:
    from aiven.db.repositories.supplier_repo import SupplierRepository
    repo = SupplierRepository(db_session)
    records = repo.list_active()
    loaded = 0
    for r in records:
        profile = SupplierProfile(
            supplier_id=r.supplier_id,
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
        register_supplier(profile)
        loaded += 1
    return loaded
