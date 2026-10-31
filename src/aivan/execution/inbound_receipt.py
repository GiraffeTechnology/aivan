"""Truthful replay of a completed inbound ledger entry, never a pending claim."""
from fastapi import HTTPException

from aivan.db.models.execution import ProcessedInboundEvent
from aivan.db.repositories.inbound_event_repo import InboundEventRepository
from aivan.schemas.rfq import RFQExecutionResult


def replay_inbound_receipt(receipt: ProcessedInboundEvent, *, trace_id: str = "") -> RFQExecutionResult:
    if receipt.event_type == InboundEventRepository.PROCESSING:
        raise HTTPException(status_code=409, detail={
            "code": "INBOUND_OUTCOME_UNCONFIRMED",
            "trace_id": trace_id,
            "message": "Earlier processing is incomplete or still running. Do not repeat business actions.",
        })
    return RFQExecutionResult(**receipt.result_json)
