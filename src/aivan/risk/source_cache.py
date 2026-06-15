from __future__ import annotations
import threading
from aivan.risk.models import FetchedPage

_cache: dict[str, FetchedPage] = {}
_lock = threading.Lock()

def get_cached(url: str) -> FetchedPage | None:
    return _cache.get(url)

def set_cached(url: str, page: FetchedPage) -> None:
    with _lock:
        _cache[url] = page

def clear_cache() -> None:
    with _lock:
        _cache.clear()
