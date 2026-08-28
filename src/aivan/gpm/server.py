"""GPM standalone FastAPI server.

Usage:
    GPM_LLM_RUNTIME_MODE=mock uv run python -m aivan.gpm.server
    GIRAFFE_DB_BASE_URL=http://localhost:9000 uv run python -m aivan.gpm.server
"""
from __future__ import annotations

import argparse

import uvicorn
from fastapi import FastAPI

from aivan.gpm.router import _init_store, get_db_client, router
from aivan.governance.runtime_policy import enforce_runtime_policy


DEFAULT_HOST = "127.0.0.1"


def validate_bind_host(host: str) -> None:
    """A non-loopback GPM bind always requires configured authentication."""

    normalized = host.strip().lower()
    if normalized in {"127.0.0.1", "localhost", "::1"}:
        return
    import os

    has_auth = bool(os.environ.get("AIVAN_AUTH_SECRET", "").strip()) or bool(
        os.environ.get("AIVAN_API_KEY", "").strip()
    ) or bool(os.environ.get("AIVAN_TENANT_API_KEYS", "").strip().strip("{}"))
    if not has_auth:
        raise RuntimeError("GPM_NON_LOOPBACK_REQUIRES_AUTH")


def create_app() -> FastAPI:
    app = FastAPI(title="AIVAN GPM", version="0.3.0")
    app.include_router(router, prefix="/api/gpm")

    @app.on_event("startup")
    def _on_startup() -> None:
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
    uvicorn.run("aivan.gpm.server:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
