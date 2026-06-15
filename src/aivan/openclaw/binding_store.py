from __future__ import annotations
import threading

_bindings: dict[str, str] = {}
_lock = threading.Lock()

def bind_conversation(conversation_id: str, project_id: str) -> None:
    with _lock:
        _bindings[conversation_id] = project_id

def get_project_id(conversation_id: str) -> str | None:
    return _bindings.get(conversation_id)

def list_bindings() -> dict[str, str]:
    return dict(_bindings)

def unbind_conversation(conversation_id: str) -> None:
    with _lock:
        _bindings.pop(conversation_id, None)
