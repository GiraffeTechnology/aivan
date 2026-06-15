from __future__ import annotations
import csv
import io
from aivan.sourcing.supplier_models import SupplierProfile
from aivan.sourcing.supplier_registry import register_supplier
from aivan.utils.ids import new_supplier_id

def import_from_csv(content: str, db_session=None) -> tuple[int, list[str]]:
    """Import suppliers from CSV string. Returns (count, errors)."""
    reader = csv.DictReader(io.StringIO(content))
    imported = 0
    errors = []

    for i, row in enumerate(reader):
        try:
            supplier_id = row.get("supplier_id", "").strip() or new_supplier_id()
            name = row.get("name", "").strip()
            if not name:
                errors.append(f"Row {i+1}: missing name")
                continue

            def parse_list(val: str) -> list[str]:
                if not val:
                    return []
                return [v.strip() for v in val.split("|") if v.strip()]

            def parse_int(val: str, default: int = 0) -> int:
                try:
                    return int(val.strip()) if val.strip() else default
                except (ValueError, AttributeError):
                    return default

            def parse_float(val: str, default: float = 0.0) -> float:
                try:
                    return float(val.strip()) if val.strip() else default
                except (ValueError, AttributeError):
                    return default

            profile = SupplierProfile(
                supplier_id=supplier_id,
                name=name,
                company_type=row.get("company_type", "").strip(),
                categories=parse_list(row.get("categories", "")),
                capabilities=parse_list(row.get("capabilities", "")),
                materials=parse_list(row.get("materials", "")),
                moq_min=parse_int(row.get("moq_min", "0")),
                moq_max=parse_int(row.get("moq_max", "0")),
                daily_capacity=parse_int(row.get("daily_capacity", "0")),
                monthly_capacity=parse_int(row.get("monthly_capacity", "0")),
                region=row.get("region", "").strip(),
                country=row.get("country", "").strip(),
                languages=parse_list(row.get("languages", "en")),
                channels=parse_list(row.get("channels", "email")),
                email=row.get("email", "").strip(),
                openclaw_peer_id=row.get("openclaw_peer_id", "").strip(),
                payment_terms=row.get("payment_terms", "").strip(),
                incoterms_supported=parse_list(row.get("incoterms_supported", "FOB")),
                logistics_modes=parse_list(row.get("logistics_modes", "sea")),
                quality_score=parse_float(row.get("quality_score", "0.7")),
                delivery_score=parse_float(row.get("delivery_score", "0.7")),
                price_score=parse_float(row.get("price_score", "0.7")),
                past_performance_score=parse_float(row.get("past_performance_score", "0.0")),
                risk_tags=parse_list(row.get("risk_tags", "")),
                notes=row.get("notes", "").strip(),
                active=row.get("active", "true").strip().lower() != "false",
            )

            register_supplier(profile)

            if db_session is not None:
                from aivan.db.repositories.supplier_repo import SupplierRepository
                repo = SupplierRepository(db_session)
                repo.upsert(supplier_id, {
                    "name": profile.name,
                    "company_type": profile.company_type,
                    "categories_json": profile.categories,
                    "capabilities_json": profile.capabilities,
                    "materials_json": profile.materials,
                    "moq_min": profile.moq_min,
                    "moq_max": profile.moq_max,
                    "daily_capacity": profile.daily_capacity,
                    "monthly_capacity": profile.monthly_capacity,
                    "region": profile.region,
                    "country": profile.country,
                    "languages_json": profile.languages,
                    "channels_json": profile.channels,
                    "email": profile.email,
                    "openclaw_peer_id": profile.openclaw_peer_id,
                    "payment_terms": profile.payment_terms,
                    "incoterms_json": profile.incoterms_supported,
                    "logistics_modes_json": profile.logistics_modes,
                    "quality_score": profile.quality_score,
                    "delivery_score": profile.delivery_score,
                    "price_score": profile.price_score,
                    "past_performance_score": profile.past_performance_score,
                    "risk_tags_json": profile.risk_tags,
                    "notes": profile.notes,
                    "active": profile.active,
                })
            imported += 1
        except Exception as e:
            errors.append(f"Row {i+1}: {e}")

    return imported, errors

def import_from_csv_file(path: str, db_session=None) -> tuple[int, list[str]]:
    with open(path, "r", encoding="utf-8") as f:
        return import_from_csv(f.read(), db_session)
