from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from aivan.app.ui_catalog import (
    GENERATED_LOCALES,
    canonical_payload,
    catalog_etag,
    load_generated_catalog,
)


router = APIRouter(prefix="/api/ui/catalogs", tags=["ui-catalogs"])


def _response(
    request: Request,
    payload: dict,
    *,
    cache_control: str = "public, max-age=60, must-revalidate",
) -> Response:
    etag = catalog_etag(payload)
    headers = {
        "Cache-Control": cache_control,
        "ETag": etag,
        "Vary": "Accept-Encoding",
    }
    if request.headers.get("if-none-match", "").strip() == etag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(payload, headers=headers)


@router.get("/{locale}")
def get_ui_catalog(locale: str, request: Request):
    """Serve a fixed English manifest or a validated generated catalog.

    This public GET never accepts source text and never invokes a translator.
    A cache miss fails closed so anonymous traffic cannot trigger translation.
    """

    normalized = locale.strip().lower()
    candidate_sha = os.environ.get("AIVAN_CANDIDATE_SHA", "").strip()
    requested_candidate = request.query_params.get("candidate", "").strip()
    if requested_candidate and requested_candidate != candidate_sha:
        raise HTTPException(status_code=409, detail={"error": "UI_CATALOG_CANDIDATE_MISMATCH"})
    if normalized == "en":
        return _response(
            request,
            canonical_payload(candidate_sha),
            cache_control="no-cache, no-store, must-revalidate",
        )
    if normalized not in GENERATED_LOCALES:
        raise HTTPException(status_code=404, detail={"error": "UI_CATALOG_UNSUPPORTED"})
    try:
        payload = load_generated_catalog(normalized, candidate_sha=candidate_sha)
    except ValueError:
        raise HTTPException(status_code=503, detail={"error": "UI_CATALOG_NOT_READY"}) from None
    return _response(request, payload)
