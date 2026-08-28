"""GPM standalone FastAPI server.

Usage:
    GPM_LLM_RUNTIME_MODE=mock uv run python -m aivan.gpm.server
    GIRAFFE_DB_BASE_URL=http://localhost:9000 uv run python -m aivan.gpm.server
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import sys
from collections.abc import Mapping, Sequence

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from aivan.governance.runtime_policy import enforce_runtime_policy
from aivan.gpm.router import _init_store, get_db_client, router


DEFAULT_HOST = "127.0.0.1"
PUBLIC_BIND_AUTH_ERROR = "GPM_NON_LOOPBACK_REQUIRES_HMAC_AUTH"


def _normalized_host(host: str) -> str:
    value = host.strip().lower()
    if value.startswith("[") and "]" in value:
        return value[1 : value.index("]")]
    if value.count(":") == 1:
        name, port = value.rsplit(":", 1)
        if port.isdigit():
            return name
    return value


def is_loopback_host(host: str) -> bool:
    """Return true only for an explicit loopback address or localhost."""

    normalized = _normalized_host(host)
    if normalized in {"127.0.0.1", "localhost", "::1"}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _argv_bind_host(argv: Sequence[str]) -> str:
    """Read common ASGI server host/bind flags without trusting a default."""

    for index, token in enumerate(argv):
        if token in {"--host", "--bind", "-b"} and index + 1 < len(argv):
            return _normalized_host(argv[index + 1])
        for prefix in ("--host=", "--bind="):
            if token.startswith(prefix):
                return _normalized_host(token[len(prefix) :])
    return ""


def resolve_bind_host(
    explicit_host: str | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    argv: Sequence[str] | None = None,
) -> str:
    """Resolve the effective bind across CLI and direct ASGI startup paths."""

    if explicit_host is not None and explicit_host.strip():
        return _normalized_host(explicit_host)
    command_host = _argv_bind_host(argv if argv is not None else sys.argv)
    if command_host:
        return command_host
    values = environment if environment is not None else os.environ
    configured_host = values.get("AIVAN_GPM_BIND_HOST", "").strip()
    return _normalized_host(configured_host) if configured_host else DEFAULT_HOST


def validate_bind_host(
    host: str, *, environment: Mapping[str, str] | None = None
) -> None:
    """Require the authentication profile that GPM actually enforces publicly."""

    if is_loopback_host(host):
        return
    values = environment if environment is not None else os.environ
    if not values.get("AIVAN_AUTH_SECRET", "").strip():
        raise RuntimeError(PUBLIC_BIND_AUTH_ERROR)


def _network_scope_host(request: Request) -> str:
    server = request.scope.get("server")
    if not isinstance(server, (tuple, list)) or not server:
        return ""
    host = str(server[0]).strip()
    try:
        ipaddress.ip_address(_normalized_host(host))
    except ValueError:
        # Starlette's in-process TestClient uses the non-network sentinel
        # "testserver". Real ASGI sockets expose a numeric local address.
        return ""
    return host


def create_app(*, bind_host: str | None = None) -> FastAPI:
    app = FastAPI(title="AIVAN GPM", version="0.3.0")
    app.include_router(router, prefix="/api/gpm")
    app.state.gpm_bind_host = DEFAULT_HOST

    @app.middleware("http")
    async def _enforce_actual_bind_auth(request: Request, call_next):
        """Catch public sockets even when the ASGI launcher hid its bind flags."""

        actual_host = _network_scope_host(request)
        if actual_host:
            try:
                validate_bind_host(actual_host)
            except RuntimeError:
                return JSONResponse(
                    status_code=503,
                    content={"error": PUBLIC_BIND_AUTH_ERROR},
                )
        return await call_next(request)

    @app.on_event("startup")
    def _on_startup() -> None:
        effective_host = resolve_bind_host(bind_host)
        validate_bind_host(effective_host)
        app.state.gpm_bind_host = effective_host
        enforce_runtime_policy(component="aivan-gpm")
        _init_store()
        app.state.giraffe_db_client = get_db_client()

    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="AIVAN GPM Server")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    enforce_runtime_policy(component="aivan-gpm")
    validate_bind_host(args.host)
    uvicorn.run(
        create_app(bind_host=args.host),
        host=args.host,
        port=args.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
