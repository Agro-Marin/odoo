import logging
from typing import Any

from .base_lru_cache import BaseLRUCache
from .registry_singleton import registry_singleton

_logger = logging.getLogger(__name__)

_CLEANUP_METHODS = ("disconnect", "close", "stop", "shutdown", "terminate")


class ConnectionManager(BaseLRUCache):
    def __init__(self, max_connections: int = 1000):
        super().__init__(
            max_size=max_connections, ttl_hours=None, use_reentrant_lock=True
        )
        _logger.info(
            "ConnectionManager initialized: max_connections=%d",
            max_connections,
        )

    def __del__(self):
        try:
            if self._lock.acquire(blocking=False):
                try:
                    entries = list(self._cache.items())
                    self._cache.clear()
                finally:
                    self._lock.release()
                self._evict(entries)
            else:
                _logger.warning(
                    "ConnectionManager.__del__ called while lock held - connections may not be cleaned up properly"
                )
        except Exception as e:
            _logger.error("Unexpected error in ConnectionManager.__del__: %s", e)

    def _on_evict(self, key: str, entry: dict[str, Any]) -> None:
        self._cleanup_connection(entry["value"])

    def _cleanup_connection(self, connection: Any) -> None:
        if connection is None:
            return

        for method_name in _CLEANUP_METHODS:
            method = getattr(connection, method_name, None)
            if not callable(method):
                continue
            try:
                method()
                _logger.debug("Connection closed via %s() method", method_name)
                return
            except Exception as e:
                _logger.warning(
                    "Error calling %s() during cleanup: %s",
                    method_name,
                    e,
                )

        _logger.debug("Connection cleanup completed (no cleanup method found)")


def get_connection_manager(env, max_connections: int = 1000) -> ConnectionManager:
    def build() -> ConnectionManager:
        _logger.info(
            "Created new connection manager for database '%s': max_connections=%d",
            env.cr.dbname,
            max_connections,
        )
        return ConnectionManager(max_connections=max_connections)

    return registry_singleton(env, "_connection_manager", build)


def invalidate_all_connections(env) -> None:
    if hasattr(env.registry, "_connection_manager"):
        removed = env.registry._connection_manager.invalidate_all()
        _logger.warning(
            "All %d connections invalidated for database '%s'",
            removed,
            env.cr.dbname,
        )
