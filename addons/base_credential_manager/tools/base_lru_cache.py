"""Base LRU Cache implementation for registry-based caches.

Provides thread-safe LRU (Least Recently Used) eviction with optional TTL support.
This base class is extended by SessionCache and ConnectionManager.

Features:
- Thread-safe operations with configurable lock type
- Max size limit with automatic LRU eviction
- Optional TTL (Time To Live) expiration
- Memory-efficient OrderedDict implementation
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

    This is a base class providing common LRU caching functionality.
    Subclasses can extend for specific use cases (sessions, connections, etc.).

    Features:
    - Max size limit with automatic eviction of least recently used entries
    - Optional TTL (Time To Live) for automatic expiration
    - Thread-safe operations with configurable lock type
    - Memory-efficient OrderedDict implementation

    Usage:
        This class should NOT be instantiated directly.
        Use subclasses like SessionCache or ConnectionManager.
    """

    def __init__(
        self,
        max_size: int = 100,
        ttl_hours: float | None = None,
        use_reentrant_lock: bool = False,
    ):
        """Initialize LRU cache.

        Args:
            max_size: Maximum number of entries to cache
            ttl_hours: Time-to-live in hours (None for no expiration)
            use_reentrant_lock: If True, use RLock instead of Lock

        """
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._max_size = max_size
        self._ttl = timedelta(hours=ttl_hours) if ttl_hours else None
        self._lock = threading.RLock() if use_reentrant_lock else threading.Lock()

    def _is_expired(self, entry: dict[str, Any]) -> bool:
        """Check if cache entry has expired.

        Args:
            entry: Cache entry dict containing 'timestamp' key

        Returns:
            bool: True if expired, False otherwise

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

        Args:
            key: Cache key

        Returns:
            dict: Cache entry or None if not found

        """
        return self._cache.get(key)

    def _set_entry(
        self,
        key: str,
        value: Any,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Set cache entry with LRU eviction.

        Args:
            key: Cache key
            value: Value to cache
            metadata: Optional metadata dict

        Returns:
            dict: Evicted entry if eviction occurred, None otherwise

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

            # Store entry with timestamp
            self._cache[key] = {
                "value": value,
                "metadata": metadata or {},
                "timestamp": fields.Datetime.now(),
            }

            # Move to end (mark as recently used)
            self._cache.move_to_end(key)

        return evicted

    def _touch(self, key: str) -> None:
        """Update entry's last-used timestamp and LRU position.

        Args:
            key: Cache key

        """
        with self._lock:
            if key in self._cache:
                self._cache[key]["timestamp"] = fields.Datetime.now()
                self._cache.move_to_end(key)

    def _remove(self, key: str) -> dict[str, Any] | None:
        """Remove entry from cache.

        Args:
            key: Cache key

        Returns:
            dict: Removed entry or None if not found

        """
        with self._lock:
            return self._cache.pop(key, None)

    def _clear(self) -> list[tuple[str, dict[str, Any]]]:
        """Clear all entries from cache.

        Returns:
            list: List of (key, entry) tuples that were cleared

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

        Args:
            filter_func: Function that takes a key and returns True to invalidate

        Returns:
            list: List of (key, entry) tuples that were invalidated

        """
        with self._lock:
            keys_to_remove = [key for key in self._cache if filter_func(key)]
            removed = [(key, self._cache.pop(key)) for key in keys_to_remove]

        if removed:
            _logger.debug("Invalidated %d cache entries matching filter", len(removed))

        return removed

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            dict: Cache statistics (size, max_size, ttl_hours, usage_pct)

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
