import os
import re

from fastapi import Request


_SHA = re.compile(r"^[0-9a-f]{40}$")


async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
        "form-action 'self'; object-src 'none'; script-src 'self'; "
        "style-src 'self'; img-src 'self' data:"
    )
    candidate = os.environ.get("AIVAN_CANDIDATE_SHA", "").strip()
    if _SHA.fullmatch(candidate):
        response.headers["X-AIVAN-Candidate-SHA"] = candidate
    if request.url.path.startswith("/api/session"):
        response.headers["Cache-Control"] = "no-store"
    return response
