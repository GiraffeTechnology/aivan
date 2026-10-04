"""Choose listening ports automatically.

No port is fixed in advance and no port allowlist is required. A server binds
the requested port when one is given and free; otherwise the operating system
assigns an unused one. Ports that the deployment environment reserves for other
services are listed in ``AIVAN_RESERVED_PORTS`` (comma-separated) and are never used.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

RESERVED_PORTS_ENV = "AIVAN_RESERVED_PORTS"
_AUTO_ATTEMPTS = 16


def parse_reserved_ports(raw: str | None) -> frozenset[int]:
    """Parse a comma-separated reserved-port list."""

    items = (raw or "").replace(" ", "").split(",")
    return frozenset(int(item) for item in items if item.isdigit())


def reserved_ports() -> frozenset[int]:
    """Return the ports this environment reserves for other services."""

    return parse_reserved_ports(os.environ.get(RESERVED_PORTS_ENV))


def usable_port(value: object, reserved: frozenset[int] | None = None) -> int | None:
    """Return ``value`` as a TCP port if it is valid and not reserved."""

    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    blocked = reserved_ports() if reserved is None else reserved
    return port if 0 < port < 65536 and port not in blocked else None


def bind_listening_socket(host: str, requested: object = None) -> socket.socket:
    """Bind ``host`` on the requested port if free, else on an OS-assigned one."""

    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    preferred = usable_port(requested)
    candidates = ([preferred] if preferred else []) + [0] * _AUTO_ATTEMPTS
    reserved = reserved_ports()
    for port in candidates:
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            sock.close()
            continue
        if sock.getsockname()[1] in reserved:
            sock.close()
            continue
        return sock
    raise RuntimeError(f"no usable port could be bound on {host}")


def record_port(port: int, *, env_var: str, file_env_var: str) -> None:
    """Publish the chosen port to this process and, if configured, a port file."""

    os.environ[env_var] = str(port)
    port_file = os.environ.get(file_env_var, "").strip()
    if port_file:
        path = Path(port_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{port}\n", encoding="utf-8")


def serve(app: object, *, host: str, requested: object, env_var: str, file_env_var: str) -> None:
    """Run ``app`` with uvicorn on an automatically chosen port."""

    import uvicorn

    sock = bind_listening_socket(host, requested)
    port = sock.getsockname()[1]
    record_port(port, env_var=env_var, file_env_var=file_env_var)
    print(f"Listening on {host}:{port}", flush=True)
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, reload=False))
    server.run(sockets=[sock])
