"""Authenticated case-scoped association read, not an execution API proxy."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from aivan.api.request_context import RequestContext, resolve_request_context
from aivan.api.execution_read_routes import router as execution_read_router
from aivan.integrations.execution_read import ExecutionReadClient, ExecutionReadError
from aivan.db.session import get_db
from aivan.integrations.execution_association import (
    ExecutionAssociationError,
    ExecutionAssociationReader,
)
from aivan.integrations.order_confirmation import (
    GiraffeDBOrderConfirmationClient,
    OrderConfirmationError,
)

router = APIRouter()

router.include_router(execution_read_router)


def _context(request: Request) -> RequestContext:
    return resolve_request_context(request)


@router.get("/cases/{case_id}/execution-association")
def get_execution_association(
    case_id: str,
    response: Response,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_context),
):
    from aivan.api.workbench_routes import _get_case

    # Current case ACL is checked before constructing or calling any provider.
    project = _get_case(db, context, case_id)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "Cookie, Authorization, X-AIVAN-API-Key"
    requirement = project.requirement_json or {}
    confirmation = requirement.get("order_confirmation")
    graph = requirement.get("giraffe_db_graph")
    if not isinstance(confirmation, dict) or confirmation.get("status") != "confirmed":
        return {"schema_version": "aivan.execution-association.v1", "case_id": case_id,
                "status": "unavailable", "reason": "EXECUTION_SOURCE_NOT_CONFIRMED",
                "local_order_id": None, "local_project_id": None,
                "execution_reads_available": False, "readback_verified": False}
    if not isinstance(graph, dict):
        raise HTTPException(409, detail={"error": "EXECUTION_SOURCE_REFERENCE_INVALID",
                                         "trace_id": context.trace_id})
    try:
        client = GiraffeDBOrderConfirmationClient(
            tenant_id=context.tenant_id, trace_id=context.trace_id,
        )
        association = ExecutionAssociationReader(client).read(
            case_id=case_id, confirmation=confirmation, graph=graph,
        )
        if association['status'] == 'associated':
            try:
                ExecutionReadClient(context)
            except ExecutionReadError as unavailable:
                association['reason'] = unavailable.code
            else:
                # This advertises an authorized fixed route, not HTTP liveness
                # or successful execution-data retrieval. Actual GETs may fail.
                from urllib.parse import quote
                association.update(execution_reads_available=True,
                    reason='EXECUTION_READ_ROUTING_CONFIGURED', execution_readiness='not_checked',
                    execution_read_prefix=f'/api/workbench/cases/{quote(case_id, safe="")}/execution')
        return association
    except OrderConfirmationError:
        raise HTTPException(503, detail={"error": "EXECUTION_PROVIDER_CONFIGURATION_UNAVAILABLE",
                                         "trace_id": context.trace_id}) from None
    except ExecutionAssociationError as exc:
        raise HTTPException(exc.status, detail={"error": exc.code,
                                               "trace_id": context.trace_id}) from None
