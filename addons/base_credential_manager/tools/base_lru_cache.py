"""Base LRU cache for registry-based caches.

Thread-safe LRU (Least Recently Used) eviction with optional TTL support.
Extended by SessionCache and ConnectionManager.
"""

import logging
import threading
from collections import OrderedDict
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from odoo import fields

_logger = logging.getLogger(__name__)


class BaseLRUCache:
    """Thread-safe LRU cache with optional TTL support.

    Base class providing common LRU caching functionality; extend it via
    subclasses like SessionCache or ConnectionManager rather than
    instantiating directly.
    """

    def __init__(
        self,
        max_size: int = 100,
        ttl_hours: float | None = None,
        use_reentrant_lock: bool = False,
    ):
        """Initialize LRU cache.

        :param max_size: Maximum number of entries to cache
        :param ttl_hours: Time-to-live in hours (None for no expiration)
        :param use_reentrant_lock: If True, use RLock instead of Lock
        """
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._max_size = max_size
        self._ttl = timedelta(hours=ttl_hours) if ttl_hours else None
        self._lock = threading.RLock() if use_reentrant_lock else threading.Lock()

    def _is_expired(self, entry: dict[str, Any]) -> bool:
        """Check if cache entry has expired.

        :param entry: Cache entry dict containing 'timestamp' key
        :return: True if expired, False otherwise
        :rtype: bool
        """
        if not self._ttl:
            return False
        timestamp = entry.get("timestamp")
        if not timestamp:
            return False
        return fields.Datetime.now() - timestamp > self._ttl

    def _get_entry(self, key: str) -> dict[str, Any] | None:
        """Get raw cache entry (internal use).

        Does NOT update LRU ordering or check expiration.

        :param key: Cache key
        :return: Cache entry or None if not found
        :rtype: dict
        """
        return self._cache.get(key)

    def _set_entry(
        self,
        key: str,
        value: Any,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Set cache entry with LRU eviction.

        :param key: Cache key
        :param value: Value to cache
        :param metadata: Optional metadata dict
        :return: Evicted entry if eviction occurred, None otherwise
        :rtype: dict
        """
        evicted = None

        with self._lock:
            # LRU eviction: Remove oldest if at capacity
            if len(self._cache) >= self._max_size and key not in self._cache:
                oldest_key = next(iter(self._cache))
                evicted = self._cache.pop(oldest_key)
                _logger.debug(
                    "LRU evicting oldest entry: %s (size: %d/%d)",
                    oldest_key,
                    len(self._cache),
                    self._max_size,
                )

            now = fields.Datetime.now()
            # Store entry. 'timestamp' tracks last use (updated by _touch);
            # 'created_at' survives overwrites of the same key so consumers
            # like ConnectionManager.get_metadata can report a real creation
            # time instead of echoing the last-used time.
            existing = self._cache.get(key)
            self._cache[key] = {
                "value": value,
                "metadata": metadata or {},
                "timestamp": now,
                "created_at": existing["created_at"] if existing else now,
            }

            # Move to end (mark as recently used)
            self._cache.move_to_end(key)

        return evicted

    def _touch(self, key: str) -> None:
        """Update entry's last-used timestamp and LRU position.

        :param key: Cache key
        """
        with self._lock:
            if key in self._cache:
                self._cache[key]["timestamp"] = fields.Datetime.now()
                self._cache.move_to_end(key)

    def _remove(self, key: str) -> dict[str, Any] | None:
        """Remove entry from cache.

        :param key: Cache key
        :return: Removed entry or None if not found
        :rtype: dict
        """
        with self._lock:
            return self._cache.pop(key, None)

    def _clear(self) -> list[tuple[str, dict[str, Any]]]:
        """Clear all entries from cache.

        :return: List of (key, entry) tuples that were cleared
        :rtype: list
        """
        with self._lock:
            entries = list(self._cache.items())
            self._cache.clear()
            return entries

    def _invalidate_matching(
        self,
        filter_func: Callable[[str], bool],
    ) -> list[tuple[str, dict[str, Any]]]:
        """Invalidate entries matching a filter condition.

        :param filter_func: Function that takes a key and returns True to invalidate
        :return: List of (key, entry) tuples that were invalidated
        :rtype: list
        """
        with self._lock:
            keys_to_remove = [key for key in self._cache if filter_func(key)]
            removed = [(key, self._cache.pop(key)) for key in keys_to_remove]

        if removed:
            _logger.debug("Invalidated %d cache entries matching filter", len(removed))

        return removed

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        :return: Cache statistics (size, max_size, ttl_hours, usage_pct)
        :rtype: dict
        """
        with self._lock:
            size = len(self._cache)
            return {
                "size": size,
                "max_size": self._max_size,
                "ttl_hours": (self._ttl.total_seconds() / 3600 if self._ttl else None),
                "usage_pct": (
                    (size / self._max_size * 100) if self._max_size > 0 else 0
                ),
            }

    def __len__(self) -> int:
        """Return number of entries in cache."""
        return len(self._cache)

    def __contains__(self, key: str) -> bool:
        """Check if key exists in cache (doesn't check expiration)."""
        return key in self._cache
