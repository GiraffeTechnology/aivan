"""CI guard: no code path may bypass the Token Guard or hardcode a host (PRD §7.8, §9.7).

  * Direct Ollama endpoint paths (``/api/chat`` / ``/api/generate``) may appear
    only inside the guard adapter — nowhere else in ``src/aivan``.
  * The Ollama port ``11434`` may appear only as a localhost placeholder.
  * No routable IPv4 literal may be hardcoded anywhere in ``src`` or ``tests``
    (only the loopback ``127.0.0.1`` and wildcard ``0.0.0.0`` are allowed);
    real hosts come from ``OLLAMA_BASE_URL`` / env, never source.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "aivan"
TESTS = ROOT / "tests"

ADAPTER = SRC / "llm" / "guard.py"
ALLOWED_IPS = {"127.0.0.1", "0.0.0.0"}
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _py_files(*roots):
    for root in roots:
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path


def _is_ipv4(token: str) -> bool:
    parts = token.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


def test_no_direct_ollama_endpoint_outside_adapter():
    offenders = []
    for path in _py_files(SRC):
        if path == ADAPTER:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "/api/chat" in text or "/api/generate" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"Direct Ollama endpoint outside the guard adapter: {offenders}"


def test_ollama_port_only_as_localhost_placeholder():
    offenders = []
    for path in _py_files(SRC, TESTS):
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if "11434" in line and "127.0.0.1" not in line and "localhost" not in line:
                offenders.append(f"{path.relative_to(ROOT)}:{i}")
    assert not offenders, f"Ollama port 11434 used without a localhost placeholder: {offenders}"


def test_no_hardcoded_routable_ip_in_src_or_tests():
    offenders = []
    for path in _py_files(SRC, TESTS):
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            for token in _IPV4.findall(line):
                if _is_ipv4(token) and token not in ALLOWED_IPS:
                    offenders.append(f"{path.relative_to(ROOT)}:{i} -> {token}")
    assert not offenders, f"Hardcoded routable IP literal(s) found: {offenders}"


@pytest.mark.parametrize("required", ["stream", "num_predict"])
def test_guard_adapter_enforces_stream_and_budget(required):
    # The adapter must set the streamed call and inject the output budget.
    text = ADAPTER.read_text(encoding="utf-8")
    assert required in text
