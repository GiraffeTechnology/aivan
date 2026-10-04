"""Opt-in current-user systemd integration. Never enable lingering or root services."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import time


def quote(value: str) -> str:
    if any(ord(char) < 32 for char in value):
        raise ValueError("Systemd paths must not contain control characters")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def unit_identity(root: Path):
    identifier = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:12]
    return f"myaivan-{identifier}.service", f"# Managed MyAivan installation {identifier}"


def unit_text(root: Path) -> str:
    _name, marker = unit_identity(root)
    python = quote(str(root / "current/runtime/bin/python3"))
    runtime = quote(str(root / "current/runtime.py"))
    prefix = quote(str(root))
    return f"""{marker}
[Unit]
Description=MyAivan integrated web and dependency services
After=network.target

[Service]
Type=simple
WorkingDirectory={prefix}
ExecStart={python} -B -I {runtime} --prefix {prefix} serve
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
KillMode=control-group
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=default.target
"""


def systemctl(*args):
    try:
        result = subprocess.run(["systemctl", "--user", *args], check=False, capture_output=True, text=True, timeout=45)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Current-user systemd is unavailable; the working installation was retained") from exc
    if result.returncode:
        raise RuntimeError("Current-user systemd operation failed; no system-wide or lingering settings were changed")


def install(root, *, stop, start, status, wait_healthy, write_json):
    # Probe first, before touching files or the running manual supervisor.
    systemctl("show-environment")
    name, marker = unit_identity(root)
    units = Path.home() / ".config/systemd/user"
    units.mkdir(parents=True, exist_ok=True)
    path = units / name
    if path.is_symlink() or (path.exists() and not path.read_text().startswith(marker + "\n")):
        raise RuntimeError("Refusing to replace an unrecognized systemd unit")
    previous = path.read_text() if path.exists() else None
    was_running = status(root)["running"]
    content = unit_text(root)
    temporary = path.with_suffix(".service.new")
    if temporary.is_symlink():
        raise RuntimeError("Unsafe systemd staging file")
    temporary.write_text(content)
    temporary.chmod(0o600)
    temporary.replace(path)
    stop(root)
    try:
        systemctl("daemon-reload")
        systemctl("enable", "--now", name)
        deadline = time.monotonic() + 45
        while not status(root)["running"] and time.monotonic() < deadline:
            time.sleep(0.1)
        wait_healthy(root)
    except Exception:
        try:
            systemctl("disable", "--now", name)
        finally:
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(previous)
            systemctl("daemon-reload")
            if was_running:
                start(root)
        raise
    write_json(root / "systemd.json", {"unit": name, "path": str(path)})
    return {"service_installed": name, "scope": "current_user", "autostart": "when_the_existing_user_manager_starts", "lingering_changed": False, "actual_reboot_test": "not_performed"}


def managed_record(root):
    record = json.loads((root / "systemd.json").read_text())
    name, marker = unit_identity(root)
    expected = Path.home() / ".config/systemd/user" / name
    if record != {"unit": name, "path": str(expected)} or expected.is_symlink():
        raise ValueError("Invalid managed systemd identity")
    if not expected.exists() or not expected.read_text().startswith(marker + "\n"):
        raise ValueError("Managed systemd unit was replaced; no service was changed")
    return name, expected


def start_registered(root):
    name, _path = managed_record(root)
    systemctl("start", name)


def uninstall(root, *, stop):
    record_path = root / "systemd.json"
    if not record_path.exists():
        return {"service_installed": False}
    name, expected = managed_record(root)
    systemctl("disable", "--now", name)
    stop(root)
    expected.unlink(missing_ok=True)
    systemctl("daemon-reload")
    record_path.unlink()
    return {"service_uninstalled": name, "data_retained": True, "lingering_changed": False}
