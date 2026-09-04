"""
Tiny TTL cache (memory + JSON on disk).

Used for market candles, news headlines and LLM sentiment results. The disk
layer means restarting the panel or running `main.py signal` twice in a row
does not hammer the exchange / news APIs, and `read_stale` lets a network
failure fall back to the last good snapshot instead of showing nothing.
"""

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

CACHE_ROOT = Path(__file__).resolve().parent.parent / "data" / "cache"
MEMORY_MAX = 256


class TTLCache:
    """Two-level cache: process memory, then a JSON file per key."""

    def __init__(self, namespace: str, base_dir: Optional[Path] = None):
        self.namespace = namespace
        self.base_dir = Path(base_dir) if base_dir else CACHE_ROOT
        self._memory: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.RLock()

    # -- keys / paths -------------------------------------------------
    def _mem_key(self, key: str) -> str:
        return f"{self.namespace}:{key}"

    def file_for(self, key: str) -> Path:
        digest = hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:24]
        folder = self.base_dir / self.namespace
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{digest}.json"

    # -- reads --------------------------------------------------------
    def read(self, key: str) -> Tuple[Optional[Any], Optional[float]]:
        """Return (value, age_seconds) from memory or disk, or (None, None)."""
        mem_key = self._mem_key(key)
        now = time.time()
        with self._lock:
            hit = self._memory.get(mem_key)
        if hit is not None:
            value, stored_at = hit
            return value, now - stored_at
        path = self.file_for(key)
        if not path.exists():
            return None, None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            value = payload["value"]
            stored_at = float(payload["stored_at"])
        except Exception:  # noqa: BLE001 - corrupt cache is simply ignored
            return None, None
        with self._lock:
            if len(self._memory) >= MEMORY_MAX:
                self._memory.pop(next(iter(self._memory)), None)
            self._memory[mem_key] = (value, stored_at)
        return value, now - stored_at

    def read_fresh(self, key: str, ttl: float) -> Optional[Any]:
        value, age = self.read(key)
        if value is None:
            return None
        if ttl is not None and ttl >= 0 and age is not None and age > ttl:
            return None
        return value

    def read_stale(self, key: str) -> Optional[Any]:
        value, _ = self.read(key)
        return value

    # -- writes -------------------------------------------------------
    def write(self, key: str, value: Any) -> None:
        now = time.time()
        with self._lock:
            if len(self._memory) >= MEMORY_MAX:
                self._memory.pop(next(iter(self._memory)), None)
            self._memory[self._mem_key(key)] = (value, now)
        path = self.file_for(key)
        try:
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"stored_at": now, "value": value}), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:  # pragma: no cover - read-only fs, etc.
            logger.debug("cache write failed for %s: %s", key, exc)

    def clear(self) -> int:
        with self._lock:
            self._memory.clear()
        folder = self.base_dir / self.namespace
        removed = 0
        if folder.exists():
            for path in folder.glob("*.json"):
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed

    # -- convenience --------------------------------------------------
    def get_or_fetch(self, key: str, ttl: float, fetch: Callable[[], Any], *,
                     stale_on_error: bool = True) -> Tuple[Any, str]:
        """Return (value, source) where source ∈ fresh|stale|fetched|error."""
        fresh = self.read_fresh(key, ttl)
        if fresh is not None:
            return fresh, "fresh"
        try:
            value = fetch()
        except Exception as exc:  # noqa: BLE001 - any upstream failure
            stale = self.read_stale(key) if stale_on_error else None
            if stale is not None:
                logger.info("cache: using stale value for %s (%s)", key, exc)
                return stale, "stale"
            raise
        if value is not None:
            self.write(key, value)
        return value, "fetched"


#: one cache instance per namespace, shared process-wide
_INSTANCES: Dict[str, TTLCache] = {}
_INSTANCES_LOCK = threading.Lock()


def cache_for(namespace: str) -> TTLCache:
    with _INSTANCES_LOCK:
        cache = _INSTANCES.get(namespace)
        if cache is None:
            cache = TTLCache(namespace)
            _INSTANCES[namespace] = cache
        return cache
