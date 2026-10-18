"""Fixed authenticated execution GET resources for an already-associated case."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from aivan.api.request_context import resolve_request_context
from aivan.db.session import get_db
from aivan.integrations.execution_read import ExecutionReadClient, ExecutionReadError

router = APIRouter()


def _read(case_id, resource, request, db, shipment_id=None):
    from aivan.api.execution_association_routes import get_execution_association
    from aivan.api.workbench_routes import _get_case
    context = resolve_request_context(request)
    # ACL and permitted signed actor are checked before any provider/JWT call.
    _get_case(db, context, case_id)
    try:
        client = ExecutionReadClient(context)
        association = get_execution_association(case_id, Response(), db, context)
        upstream = client.read(association, resource, shipment_id=shipment_id)
        return Response(content=upstream.content, status_code=200, media_type='application/json',
                        headers={'Cache-Control': 'no-store', 'Vary': 'Cookie, Authorization, X-AIVAN-API-Key'})
    except ExecutionReadError as exc:
        raise HTTPException(exc.status, detail={'error': exc.code, 'trace_id': context.trace_id}) from None


@router.get('/cases/{case_id}/execution/{resource}')
def read_execution(case_id: str, resource: Literal['order', 'production', 'qc', 'events'],
                   request: Request, db: Session = Depends(get_db)):
    return _read(case_id, resource, request, db)


@router.get('/cases/{case_id}/execution/shipments/{shipment_id}')
def read_execution_shipment(case_id: str, shipment_id: UUID, request: Request,
                            db: Session = Depends(get_db)):
    return _read(case_id, 'shipment', request, db, str(shipment_id))
