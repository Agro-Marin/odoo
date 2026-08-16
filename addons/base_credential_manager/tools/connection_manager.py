"""Process-global, thread-safe manager for long-lived protocol connections.

Handles connection lifecycle (LRU eviction, metadata tracking, graceful
cleanup) for persistent protocols such as MQTT, WebSocket and Modbus TCP.
For HTTP sessions use SessionCache instead (see session_cache.py); this
manager is specifically for persistent protocol connections, not HTTP.
"""

import logging
import threading
from collections.abc import Callable
from typing import Any

from .base_lru_cache import BaseLRUCache

_logger = logging.getLogger(__name__)


class ConnectionManager(BaseLRUCache):
    """Process-global connection pool for long-lived connections.

    Extends BaseLRUCache with graceful connection cleanup, metadata tracking,
    and no TTL (connections stay open until evicted or removed).
    """

    def __init__(self, max_connections: int = 1000):
        """Initialize connection manager.

        :param int max_connections: maximum number of connections to store;
            oldest connections are evicted when the limit is reached.
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
        """Cleanup all connections when the manager is garbage collected."""
        try:
            # Non-blocking acquire avoids deadlocks during garbage collection.
            # Note this is a backstop, not the primary teardown path: a manager
            # holding a thread-backed connection is not reliably collectable
            # (see :func:`get_connection_manager`). Use
            # :meth:`invalidate_all` for deterministic cleanup.
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

        :param env: Odoo environment (unused; kept for API consistency)
        :param str key: unique connection key (e.g. 'device:123', 'mqtt:sensor-001')
        :param connection: connection object (MQTT client, WebSocket app, etc.)
        :param metadata: additional metadata for debugging/tracking
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
        """Get connection and update its last-used timestamp.

        :param env: Odoo environment (unused; kept for API consistency)
        :param str key: connection key
        :return: connection object if found, None otherwise
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

        :param env: Odoo environment (unused; kept for API consistency)
        :param str key: connection key
        :return: True if the connection was removed, False if not found
        :rtype: bool
        """
        entry = self._remove(key)

        if entry:
            self._cleanup_connection(entry["value"])
            _logger.info("Connection removed: %s", key)
            return True

        _logger.debug("Connection not found for removal: %s", key)
        return False

    def get_metadata(self, env, key: str) -> dict[str, Any] | None:
        """Get connection metadata without retrieving the connection.

        :param env: Odoo environment (unused; kept for API consistency)
        :param str key: connection key
        :return: dict with created_at, last_used and custom metadata, or None
            if the key is not found
        :rtype: dict | None
        """
        with self._lock:
            entry = self._get_entry(key)
            if entry:
                return {
                    # created_at is preserved across overwrites by
                    # BaseLRUCache._set_entry; fall back to the last-used
                    # timestamp for entries written before that field existed.
                    "created_at": entry.get("created_at") or entry["timestamp"],
                    "last_used": entry["timestamp"],
                    "metadata": entry["metadata"],
                }
            return None

    def list_connections(self, env=None) -> list[str]:
        """List all connection keys.

        :param env: Odoo environment (unused; kept for API consistency)
        :return: list of connection keys
        :rtype: list
        """
        with self._lock:
            return list(self._cache.keys())

    def get_stats(self, env=None) -> dict[str, Any]:
        """Get connection manager statistics.

        :param env: Odoo environment (unused; kept for API consistency)
        :return: dict with total_connections and max_connections
        :rtype: dict
        """
        base_stats = super().get_stats()
        return {
            "total_connections": base_stats["size"],
            "max_connections": base_stats["max_size"],
        }

    def invalidate_all(self) -> None:
        """Invalidate all connections and cleanup gracefully."""
        # The deterministic teardown entry point: call this from a consumer's
        # ``_register_hook`` to drop connections on module upgrade/registry
        # reload, which no longer happens implicitly.
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

        :param filter_func: callable taking a key and returning True to invalidate it
        :return: number of connections invalidated
        :rtype: int
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
        """Gracefully close a connection and stop any background network thread.

        :param connection: connection object to cleanup
        """
        if connection is None:
            return

        # Stop the background network loop FIRST, before the protocol-level
        # disconnect. This targets paho-mqtt specifically: its ``loop_start()``
        # thread survives ``disconnect()`` and auto-reconnects on its own, so
        # dropping our last reference does not stop it — it only makes it
        # unreachable. An unreachable client that keeps reconnecting with the
        # same client_id collides with its own replacement on the broker (AWS
        # IoT enforces unique client IDs) and the broker starts refusing
        # connections. ``loop_stop()`` joins the thread; paho skips the join
        # when called from inside that thread, so this is safe from a callback.
        #
        # Order matters and is safe: after ``loop_stop()`` paho has set
        # ``_thread`` to None, so the ``disconnect()`` below takes paho's
        # synchronous ``loop_write()`` path — the DISCONNECT packet is still
        # sent and ``_packet_write`` closes the socket. Doing it the other way
        # round would leave the reconnect loop running between the two calls.
        #
        # Other connection types have no such thread and no ``loop_stop``:
        # websocket-client's WebSocketApp and pymodbus clients both stop
        # cleanly via ``close()`` in the loop below, and are unaffected here.
        loop_stop = getattr(connection, "loop_stop", None)
        if callable(loop_stop):
            try:
                loop_stop()
                _logger.debug("Background network loop stopped via loop_stop()")
            except Exception as e:
                _logger.warning("Error calling loop_stop() during cleanup: %s", e)

        # Then the protocol-level close. Unlike the loop stoppers above these
        # are alternatives, so stop at the first one that succeeds.
        for method_name in ("disconnect", "close", "stop", "shutdown", "terminate"):
            method = getattr(connection, method_name, None)
            if callable(method):
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


# ==================== Registry-Based Manager ====================


_managers: dict[str, ConnectionManager] = {}
_managers_lock = threading.Lock()


def get_connection_manager(env, max_connections: int = 1000) -> ConnectionManager:
    """Get or create the connection manager for this database.

    :param env: Odoo environment (provides the database name)
    :param int max_connections: maximum connections (default 1000)
    :return: connection manager instance for this database
    :rtype: ConnectionManager
    """
    # Process-global, keyed by database. This manager owns connections backed by
    # real OS threads (paho's ``loop_start()``, websocket-client's
    # ``run_forever()``), whose lifetime is the *process* — so the owning
    # container must be the process too.
    #
    # This was previously attached to ``env.registry`` on the theory that a
    # registry rebuild would garbage-collect the manager and its connections.
    # It does not, for two compounding reasons:
    #
    #   1. A paho client is wired to bound methods of the recordset that opened
    #      it (``client.on_connect = self._mqtt_on_connect``), and a bound method
    #      holds its recordset -> env -> registry -> the manager -> the client.
    #      That cycle is anchored by the live network thread, so the old registry
    #      stays reachable and ``ConnectionManager.__del__`` never runs.
    #   2. Even when cleanup does run, dropping a reference never stops a
    #      background thread (see :meth:`ConnectionManager._cleanup_connection`).
    #
    # The observed result was one leaked paho client *per device per registry
    # rebuild*, each still auto-reconnecting with the same client_id, colliding
    # with its own replacement until the broker refused every connection.
    # Keying by database preserves the per-database isolation the registry
    # provided; consumers that need teardown on module upgrade should call
    # :meth:`ConnectionManager.invalidate_all` from their ``_register_hook``.
    dbname = env.cr.dbname
    manager = _managers.get(dbname)
    if manager is not None:
        return manager

    with _managers_lock:
        # Re-check inside the lock: concurrent workers race to create the first
        # manager, and losing that race must not discard the winner's live
        # connections.
        manager = _managers.get(dbname)
        if manager is None:
            manager = ConnectionManager(max_connections=max_connections)
            _managers[dbname] = manager
            _logger.info(
                "Created new connection manager for database '%s': max_connections=%d",
                dbname,
                max_connections,
            )
        return manager


def invalidate_all_connections(env) -> None:
    """Invalidate all connections for the current database.

    :param env: Odoo environment
    """
    # WARNING: this disconnects all active connections.
    manager = _managers.get(env.cr.dbname)
    if manager is not None:
        manager.invalidate_all()
        _logger.warning("All connections invalidated for database '%s'", env.cr.dbname)
