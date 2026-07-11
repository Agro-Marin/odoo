"""Connection Manager for persistent connections (MQTT, WebSocket, Modbus, etc.).

STATUS: IN USE — consumed by ``addons/agromarin/remote/models/remote_device.py``.
(Earlier header claimed "reserved for future use"; that was stale.)

Provides centralized, thread-safe connection lifecycle management with:
- LRU eviction when connection limit reached
- Metadata tracking for debugging
- Graceful connection cleanup
- Registry-based storage (auto-cleanup on module upgrade)

INTENDED USE CASES:
- MQTT broker connections for IoT sensors (remote module)
- WebSocket connections for real-time updates
- Modbus TCP connections for industrial devices
- Redis/RabbitMQ persistent connections
- Any long-lived TCP/UDP connections

NOTE: For HTTP sessions, use SessionCache instead (see session_cache.py).
ConnectionManager is specifically for persistent protocol connections, not HTTP.
"""

import logging
from collections.abc import Callable
from typing import Any

from .base_lru_cache import BaseLRUCache

_logger = logging.getLogger(__name__)


class ConnectionManager(BaseLRUCache):
    """Registry-based connection pool for long-lived connections.

    Extends BaseLRUCache with connection-specific functionality:
    - Graceful connection cleanup (disconnect/close/stop methods)
    - Metadata tracking (protocol, device name, etc.)
    - No TTL (connections stay open until evicted or removed)

    Features:
    - Thread-safe operations with RLock
    - LRU eviction with configurable size limit
    - Metadata tracking (created_at, last_used, custom metadata)
    - Graceful connection cleanup
    - Registry-based storage (per database, auto-cleanup on module upgrade)

    Usage:
        >>> from odoo.addons.base_credential_manager.tools import get_connection_manager
        >>> manager = get_connection_manager(env)
        >>> manager.set(env, "device:123", mqtt_client, metadata={"protocol": "mqtt"})
        >>> client = manager.get(env, "device:123")
        >>> manager.remove(env, "device:123")
    """

    def __init__(self, max_connections: int = 1000):
        """Initialize connection manager.

        Args:
            max_connections: Maximum number of connections to store.
                            Oldest connections evicted when limit reached.

        """
        # Use RLock for connection manager (may need reentrant access during cleanup)
        super().__init__(
            max_size=max_connections, ttl_hours=None, use_reentrant_lock=True
        )
        _logger.info(
            "ConnectionManager initialized: max_connections=%d",
            max_connections,
        )

    def __del__(self):
        """Destructor: Cleanup all connections when manager is garbage collected.

        Called automatically when registry is rebuilt or manager is deleted.

        Note: Uses non-blocking cleanup to avoid deadlocks during garbage collection.
        """
        try:
            # Try to acquire lock without blocking (non-blocking cleanup)
            if self._lock.acquire(blocking=False):
                try:
                    connections_to_cleanup = [
                        (key, entry["value"]) for key, entry in self._cache.items()
                    ]
                    self._cache.clear()
                finally:
                    self._lock.release()

                # Cleanup outside lock
                for key, connection in connections_to_cleanup:
                    try:
                        self._cleanup_connection(connection)
                    except Exception as e:
                        _logger.error("Error in __del__ cleanup for %s: %s", key, e)
            else:
                _logger.warning(
                    "ConnectionManager.__del__ called while lock held - connections may not be cleaned up properly"
                )
        except Exception as e:
            # Don't let exceptions in __del__ propagate
            _logger.error("Unexpected error in ConnectionManager.__del__: %s", e)

    def set(
        self,
        env,
        key: str,
        connection: Any,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store connection with optional metadata.

        Args:
            env: Odoo environment (not used but kept for API consistency)
            key: Unique connection key (e.g., 'device:123', 'mqtt:sensor-001')
            connection: Connection object (MQTT client, WebSocket app, etc.)
            metadata: Additional metadata for debugging/tracking

        Example:
            >>> manager.set(
            ...     env,
            ...     "device:123",
            ...     mqtt_client,
            ...     metadata={
            ...         "protocol": "mqtt",
            ...         "device_name": "Temperature Sensor",
            ...         "broker": "mqtt.example.com",
            ...     },
            ... )

        """
        evicted = self._set_entry(key, connection, metadata)

        if evicted:
            _logger.info(
                "Connection limit reached (%d). Evicting oldest connection.",
                self._max_size,
            )
            # Cleanup evicted connection OUTSIDE lock (can take time)
            try:
                self._cleanup_connection(evicted["value"])
            except Exception as e:
                _logger.error("Error cleaning up evicted connection: %s", e)

        _logger.debug(
            "Connection stored: %s (total: %d/%d)",
            key,
            len(self),
            self._max_size,
        )

    def get(self, env, key: str) -> Any | None:
        """Get connection and update last_used timestamp.

        Args:
            env: Odoo environment (not used but kept for API consistency)
            key: Connection key

        Returns:
            Connection object if found, None otherwise

        Example:
            >>> mqtt_client = manager.get(env, "device:123")
            >>> if mqtt_client:
            ...     mqtt_client.publish("topic", "message")

        """
        with self._lock:
            entry = self._get_entry(key)
            if entry:
                self._touch(key)
                _logger.debug("Connection retrieved: %s", key)
                return entry["value"]

            _logger.debug("Connection not found: %s", key)
            return None

    def remove(self, env, key: str) -> bool:
        """Remove and cleanup connection.

        Args:
            env: Odoo environment (not used but kept for API consistency)
            key: Connection key

        Returns:
            bool: True if connection was removed, False if not found

        Example:
            >>> manager.remove(env, "device:123")

        """
        entry = self._remove(key)

        if entry:
            self._cleanup_connection(entry["value"])
            _logger.info("Connection removed: %s", key)
            return True

        _logger.debug("Connection not found for removal: %s", key)
        return False

    def get_metadata(self, env, key: str) -> dict[str, Any] | None:
        """Get connection metadata without retrieving connection.

        Args:
            env: Odoo environment (not used but kept for API consistency)
            key: Connection key

        Returns:
            dict: Metadata including created_at, last_used, custom metadata

        Example:
            >>> metadata = manager.get_metadata(env, "device:123")
            >>> print(f"Protocol: {metadata['metadata']['protocol']}")
            >>> print(f"Last used: {metadata['timestamp']}")

        """
        with self._lock:
            entry = self._get_entry(key)
            if entry:
                return {
                    "created_at": entry["timestamp"],
                    "last_used": entry["timestamp"],
                    "metadata": entry["metadata"],
                }
            return None

    def list_connections(self, env=None) -> list[str]:
        """List all connection keys.

        Args:
            env: Odoo environment (not used but kept for API consistency)

        Returns:
            list: List of connection keys

        Example:
            >>> keys = manager.list_connections(env)
            >>> print(f"Active connections: {len(keys)}")

        """
        with self._lock:
            return list(self._cache.keys())

    def get_stats(self, env=None) -> dict[str, Any]:
        """Get connection manager statistics.

        Args:
            env: Odoo environment (not used but kept for API consistency)

        Returns:
            dict: Statistics (total_connections, max_connections)

        Example:
            >>> stats = manager.get_stats(env)
            >>> print(
            ...     f"Connections: {stats['total_connections']}/{stats['max_connections']}"
            ... )

        """
        base_stats = super().get_stats()
        return {
            "total_connections": base_stats["size"],
            "max_connections": base_stats["max_size"],
        }

    def invalidate_all(self) -> None:
        """Invalidate all connections and cleanup gracefully.

        Called when registry is rebuilt or for manual cleanup.
        """
        entries = self._clear()

        # Cleanup connections OUTSIDE the lock (can take time)
        for key, entry in entries:
            try:
                self._cleanup_connection(entry["value"])
            except Exception as e:
                _logger.error("Error cleaning up connection %s: %s", key, e)

        _logger.info("Invalidated %d connections", len(entries))

    def invalidate_matching(self, filter_func: Callable[[str], bool]) -> int:
        """Invalidate connections matching a filter condition.

        Args:
            filter_func: Function that takes a key and returns True to invalidate

        Returns:
            int: Number of connections invalidated

        """
        removed = self._invalidate_matching(filter_func)

        # Cleanup connections
        for key, entry in removed:
            try:
                self._cleanup_connection(entry["value"])
            except Exception as e:
                _logger.error("Error cleaning up connection %s: %s", key, e)

        return len(removed)

    def _cleanup_connection(self, connection: Any) -> None:
        """Gracefully close connection.

        Tries common disconnect/close methods. Logs warnings if cleanup fails.

        Args:
            connection: Connection object to cleanup

        """
        if connection is None:
            return

        # Try common disconnect/close methods
        cleanup_methods = [
            "disconnect",
            "close",
            "stop",
            "shutdown",
            "terminate",
        ]

        for method_name in cleanup_methods:
            if hasattr(connection, method_name):
                try:
                    method = getattr(connection, method_name)
                    if callable(method):
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


# ==================== Registry-Based Manager ====================


def get_connection_manager(env, max_connections: int = 1000) -> ConnectionManager:
    """Get or create connection manager from registry.

    Registry-based storage ensures:
    - Automatic cleanup on module upgrade/reload (registry is rebuilt)
    - Per-database isolation (each registry = one database)
    - No stale connections after code changes
    - Thread-safe access (manager handles locking)

    Args:
        env: Odoo environment (provides access to registry)
        max_connections: Maximum connections (default: 1000)

    Returns:
        ConnectionManager: Connection manager instance for this database

    Example:
        >>> from odoo.addons.base_credential_manager.tools import get_connection_manager
        >>> manager = get_connection_manager(self.env)
        >>> manager.set(self.env, "device:123", connection)

    """
    registry = env.registry

    # Check if manager exists in registry
    if not hasattr(registry, "_connection_manager"):
        # Create new manager and attach to registry
        registry._connection_manager = ConnectionManager(
            max_connections=max_connections
        )
        _logger.info(
            "Created new connection manager for database '%s': max_connections=%d",
            env.cr.dbname,
            max_connections,
        )

    return registry._connection_manager


def invalidate_all_connections(env) -> None:
    """Invalidate all connections for the current database.

    WARNING: This will disconnect all active connections!

    Args:
        env: Odoo environment

    Example:
        >>> from odoo.addons.base_credential_manager.tools import (
        ...     invalidate_all_connections,
        ... )
        >>> invalidate_all_connections(self.env)  # Emergency cleanup

    """
    if hasattr(env.registry, "_connection_manager"):
        manager = env.registry._connection_manager
        manager.invalidate_all()
        _logger.warning("All connections invalidated for database '%s'", env.cr.dbname)
