"""Static guard: no business-semantic hardcoding in AIVAN production code (PRD §2, §18.4).

Scans ``src/aivan`` for alias tables and demo-specific semantic mappings that
would turn AIVAN from an agentic product into a scripted demo. Test fixtures,
docs, and explicitly-gated demo data are allowed and not scanned.
"""
from __future__ import annotations

import re
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "aivan"

FORBIDDEN_PATTERNS = [
    r"CITY_ALIASES",
    r"PORT_ALIASES",
    r"DESTINATION_ALIASES",
    r"SKU_ALIASES",
    r"PRODUCT_ALIASES",
    r"SUPPLIER_STUBS",
    r"东京.*Tokyo",
    r"大阪.*Osaka",
    r"格子衬衫.*plaid shirt",
    r"plaid shirt.*格子衬衫",
    r"known_sup_shenzhen_apparel",
    r"known_sup_guangzhou_textile",
]


def _production_python_files() -> list[Path]:
    return [p for p in SRC_ROOT.rglob("*.py") if "__pycache__" not in p.parts]


def test_no_forbidden_semantic_hardcoding_in_production():
    offenders: list[str] = []
    for path in _production_python_files():
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_PATTERNS:
            if re.search(pattern, text):
                offenders.append(f"{path.relative_to(SRC_ROOT.parents[1])}: /{pattern}/")
    assert not offenders, "Forbidden business-semantic hardcoding found:\n" + "\n".join(offenders)


def test_stub_suppliers_live_in_demo_data_not_src():
    # The stub supplier identifiers must exist only under data/demo, loaded behind
    # explicit config — never inlined in production source.
    demo_file = SRC_ROOT.parents[1] / "data" / "demo" / "stub_suppliers.json"
    assert demo_file.exists()
    assert "known_sup_shenzhen_apparel" in demo_file.read_text(encoding="utf-8")
