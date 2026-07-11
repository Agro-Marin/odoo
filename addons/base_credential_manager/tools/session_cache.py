"""Session Cache for HTTP session/connection reuse.

Provides thread-safe LRU caching with TTL for session objects.
Registry-based storage ensures automatic cleanup on module upgrade.

Usage:
    >>> from odoo.addons.base_credential_manager.tools import get_session_cache
    >>> cache = get_session_cache(env)
    >>> cache.set("key", session_object)
    >>> session = cache.get("key")
"""

import logging
from collections.abc import Callable
from typing import Any

from .base_lru_cache import BaseLRUCache

_logger = logging.getLogger(__name__)


class SessionCache(BaseLRUCache):
    """Thread-safe LRU cache for sessions with TTL.

    Extends BaseLRUCache with session-specific functionality:
    - TTL (Time To Live) for automatic expiration
    - Simple get/set API for session objects

    Features:
    - Max size limit with automatic eviction of least recently used entries
    - TTL (Time To Live) for automatic expiration
    - Thread-safe operations with threading.Lock
    - Memory-efficient OrderedDict implementation
    - Registry-based storage (automatic cleanup on module reload)

    Usage:
        This class should NOT be instantiated directly. Use get_session_cache(env)
        to retrieve the registry-based cache instance for the current database.

        >>> from odoo.addons.base_credential_manager.tools import get_session_cache
        >>> cache = get_session_cache(env)
        >>> cache.set("key", session_object)
        >>> session = cache.get("key")
    """

    def __init__(self, max_size: int = 100, ttl_hours: float = 1):
        """Initialize LRU session cache.

        Args:
            max_size: Maximum number of sessions to cache
            ttl_hours: Time-to-live in hours for cached sessions

        """
        # Use reentrant lock because get() calls _touch()/_remove() which also acquire lock
        super().__init__(
            max_size=max_size, ttl_hours=ttl_hours, use_reentrant_lock=True
        )
        _logger.info(
            "SessionCache initialized: max_size=%d, ttl=%.1fh",
            max_size,
            ttl_hours,
        )

    def get(self, key: str) -> Any | None:
        """Get session from cache.

        Args:
            key: Cache key

        Returns:
            Cached session object, or None if not found/expired

        """
        with self._lock:
            entry = self._get_entry(key)
            if entry is None:
                return None

            # Check expiration
            if self._is_expired(entry):
                _logger.debug("Session cache expired: %s", key)
                self._remove(key)
                return None

            # Update LRU position
            self._touch(key)
            _logger.debug("Session cache hit: %s", key)
            return entry["value"]

    def set(self, key: str, session: Any) -> None:
        """Store session in cache.

        Args:
            key: Cache key
            session: Session object to cache

        """
        evicted = self._set_entry(key, session)
        if evicted:
            _logger.debug("Session cache evicted oldest entry (size: %d)", len(self))
        _logger.debug("Session cached: %s (size: %d)", key, len(self))

    def invalidate(self, key: str | None = None) -> None:
        """Invalidate cache entry or entire cache.

        Args:
            key: Specific key to invalidate. If None, clears entire cache.

        """
        if key is None:
            entries = self._clear()
            _logger.info("Session cache cleared: %d entries removed", len(entries))
        elif self._remove(key):
            _logger.debug("Session cache invalidated: %s", key)

    def invalidate_matching(self, filter_func: Callable[[str], bool]) -> int:
        """Invalidate cache entries matching a filter condition.

        This is the PUBLIC API for selective cache invalidation.
        Use this instead of accessing _cache directly.

        Args:
            filter_func: Function that takes a cache key (str) and
                        returns True if the entry should be invalidated.

        Returns:
            int: Number of entries invalidated

        Example:
            >>> # Invalidate all entries for a specific service
            >>> cache = get_session_cache(env)
            >>> count = cache.invalidate_matching(lambda key: "stripe:" in key)
            >>> print(f"Invalidated {count} Stripe sessions")

        """
        removed = self._invalidate_matching(filter_func)
        return len(removed)


# ==================== Registry-Based Cache ====================


def get_session_cache(env, max_size: int = 100, ttl_hours: float = 1) -> SessionCache:
    """Get or create session cache from registry.

    ⚠️ ``max_size`` / ``ttl_hours`` only take effect on the call that CREATES
    the cache (first caller per worker registry). Later callers get the
    existing instance unchanged — do not rely on per-call sizing.

    ⚠️ Per-worker, not per-database. In prefork mode (``workers >= 1``) each
    worker has its own ``Registry`` and its own cache, so effective hit rate
    is at most ``1 / num_workers``. Acceptable for a pure session cache
    (worst case: redundant logins), but do not rely on this as a global
    deduplication layer.

    Registry storage still gives us:
    - Automatic cleanup on module upgrade/reload
    - Thread-safe access within a single worker
    """
    registry = env.registry

    # Check if cache exists in registry
    if not hasattr(registry, "_session_cache"):
        # Create new cache and attach to registry
        registry._session_cache = SessionCache(max_size=max_size, ttl_hours=ttl_hours)
        _logger.info(
            "Created new session cache for database '%s': max_size=%d, ttl=%.1fh",
            env.cr.dbname,
            max_size,
            ttl_hours,
        )

    return registry._session_cache


def invalidate_session_cache(env) -> None:
    """Invalidate session cache for the current database.

    Args:
        env: Odoo environment

    Note:
        Cache is automatically invalidated when registry is rebuilt (module upgrade).
        Use this method for manual cache invalidation (e.g., credential rotation).

    """
    registry = env.registry

    if hasattr(registry, "_session_cache"):
        cache = registry._session_cache
        stats = cache.get_stats()
        cache.invalidate()
        _logger.info(
            "Manually invalidated session cache for database '%s': %d entries removed",
            env.cr.dbname,
            stats["size"],
        )
