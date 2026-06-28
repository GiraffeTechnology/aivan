"""Supplier real-time state-signal layer.

Sits between enquiry dispatch and GLTG path ranking: historical performance is
the baseline, current-state signals (capacity, earliest start, load, response
behaviour) become adjustment factors fed to GLTG as ``supplier_state_overrides``.

See ``GLTG-ITERATION-SUPPLIER-SIGNAL-2026-06-27``.
"""

from aivan.supplier_signals.models import (
    EnquiryContext,
    ExtractionResult,
    LoadLevel,
    ResponseBehaviour,
    RiskFlag,
    SupplierStateSignal,
)

__all__ = [
    "EnquiryContext",
    "ExtractionResult",
    "LoadLevel",
    "ResponseBehaviour",
    "RiskFlag",
    "SupplierStateSignal",
]
