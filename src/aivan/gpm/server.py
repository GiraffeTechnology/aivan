"""GPM standalone FastAPI server.

Usage:
    GPM_LLM_RUNTIME_MODE=mock uv run python -m aivan.gpm.server
    GIRAFFE_DB_BASE_URL=http://localhost:9000 uv run python -m aivan.gpm.server
"""
from __future__ import annotations

import argparse

import uvicorn
from fastapi import FastAPI

from aivan.gpm.router import _init_store, router


def create_app() -> FastAPI:
    app = FastAPI(title="AIVAN GPM", version="0.2.0")
    app.include_router(router, prefix="/api/gpm")

    @app.on_event("startup")
    def _on_startup() -> None:
        _init_store()

    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="AIVAN GPM Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    uvicorn.run("aivan.gpm.server:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
