from __future__ import annotations

import contextlib
import hashlib
import logging
import threading
from time import monotonic
from typing import TYPE_CHECKING

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg_pool import ConnectionPool as _PsycopgPool
from psycopg_pool import PoolClosed, PoolTimeout

from odoo.release import MIN_PG_VERSION

from .utils import register_adapters

if TYPE_CHECKING:
    from .cursor import Cursor

_logger = logging.getLogger(__name__)
_logger_conn = _logger.getChild("connection")


class _SuppressKnownPoolWarnings(logging.Filter):
    """Drop known psycopg_pool log records that are not real errors.

    ``filter()`` returns ``False`` for a matched record, which removes it
    entirely (the level is not lowered — there is no demotion, only
    suppression).

    1. ``keep_in_pool=False`` warnings: When connections are intentionally
       closed before returning to the pool, psycopg_pool logs a WARNING
       about "discarding closed connection".  This is expected.

    2. "database does not exist" reconnection warnings: After a database
       is dropped, the pool may still attempt to reconnect for up to
       ``reconnect_timeout`` seconds.  These warnings are noise — the
       caller will get a ``PoolTimeout`` and the pool will be cleaned up.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "discarding closed connection" in msg:
            return False
        # Narrow to the specific PG phrase for a missing database; a broad
        # ``FATAL`` + ``does not exist`` test also swallows legitimate
        # misconfiguration signals like ``role "x" does not exist`` or
        # ``tablespace "x" does not exist``.
        return not ('database "' in msg and "does not exist" in msg)


# Guard against duplicate filters if the module is reloaded (e.g. via
# importlib.reload in test harnesses) — addFilter is not idempotent and
# each extra copy multiplies the per-log-record cost of the suppression
# check.
_psycopg_pool_logger = logging.getLogger("psycopg.pool")
if not any(
    isinstance(f, _SuppressKnownPoolWarnings) for f in _psycopg_pool_logger.filters
):
    _psycopg_pool_logger.addFilter(_SuppressKnownPoolWarnings())

MAX_IDLE_TIMEOUT = 60 * 10
MAX_LIFETIME = 3600  # recycle each pooled connection hourly (stale prep caches)

# Shared wall-clock budget for a single borrow(): the semaphore wait and the
# per-DSN getconn() both draw from this same window.  Named so the two uses in
# borrow() can never silently drift apart.
_BORROW_TIMEOUT = 30.0

# Connection failures whose cause is permanent: retrying cannot help, because
# the database, role, or password is the problem — not transient capacity.
# psycopg_pool's background worker does not know this; left alone it retries
# the failed connection until ``borrow``'s ~30s getconn budget expires, then
# surfaces an opaque ``PoolTimeout``.  The pre-flight probe in
# ``_get_or_create_pool`` raises these immediately instead, which is what makes
# ``exp_db_exist``'s ``except InvalidCatalogName`` fast path reachable again.
# NB: InvalidPassword (28P01) is NOT a subclass of
# InvalidAuthorizationSpecification (28000) in psycopg 3 — list both.
_NON_RETRYABLE_CONNECT_ERRORS: tuple[type[psycopg.Error], ...] = (
    psycopg.errors.InvalidCatalogName,  # 3D000 — database does not exist
    psycopg.errors.InvalidAuthorizationSpecification,  # 28000 — role / pg_hba rejection
    psycopg.errors.InvalidPassword,  # 28P01 — wrong password
)

# libpq connect timeout (seconds) for that probe.  Kept short: a permanent
# rejection comes back in one round-trip, so this only bounds the exotic
# "TCP SYN silently dropped" case — where we fall through to the pool's
# normal retry anyway.
_PROBE_CONNECT_TIMEOUT = 5


def _translate_connect_error(exc: psycopg.OperationalError) -> psycopg.Error | None:
    """Map an untyped connection-phase ``OperationalError`` to its precise,
    permanent psycopg class — or ``None`` when the cause may be transient.

    A connection failure crosses libpq before a SQLSTATE is parsed, so
    ``diag.sqlstate`` is ``None`` and the precise subclass
    (``InvalidCatalogName``, …) is never raised on a *connect*.  The server's
    English FATAL text is the only discriminator left — the same signal
    :class:`_SuppressKnownPoolWarnings` already keys on.  Matching fails SAFE:
    an unrecognised or localised message returns ``None`` and is left to the
    pool's retry, so a genuinely transient "connection refused"/timeout (which
    never contains these phrases) is never mistaken for permanent.

    Returning the precise class — rather than a generic error — lets callers
    such as ``exp_db_exist`` keep matching ``InvalidCatalogName`` unchanged.
    """
    msg = str(exc).lower()
    if 'database "' in msg and "does not exist" in msg:
        return psycopg.errors.InvalidCatalogName(str(exc))
    if (
        "password authentication failed" in msg
        or "no pg_hba.conf entry" in msg
        or ('role "' in msg and "does not exist" in msg)
        or "is not permitted to log in" in msg
    ):
        return psycopg.errors.InvalidAuthorizationSpecification(str(exc))
    return None


class PoolError(Exception):
    """Connection pool error."""


def _normalize_dsn_key(dsn: dict | str) -> frozenset:
    """Normalize a DSN to a hashable key for pool lookup.

    Aliases ``dbname`` → ``database``.  Folds the password into an opaque
    fingerprint so rotating the password invalidates the cached pool, but
    the cleartext never lives in memory as a dict key or log artifact.
    """
    alias_keys = {"dbname": "database"}
    if isinstance(dsn, str):
        dsn = conninfo_to_dict(dsn)
    elif "dsn" in dsn:
        # Expand a URI/conninfo entry into its components so they join the
        # key the same way keyword parameters do.  Without this the raw URI
        # string — cleartext password included — becomes part of the key
        # (and of the DEBUG/INFO pool logs), and the password-fingerprint
        # guarantee below is silently bypassed.  Explicit keywords override
        # URI components, matching psycopg's own precedence.
        uri_parts = conninfo_to_dict(dsn["dsn"])
        dsn = {**uri_parts, **{k: v for k, v in dsn.items() if k != "dsn"}}
    # BLAKE2s-64 is fast, collision-resistant enough for pool routing, and
    # avoids leaking password length information via the key repr.
    password = dsn.get("password")
    if password:
        pw_fp = hashlib.blake2s(str(password).encode(), digest_size=8).hexdigest()
    else:
        pw_fp = ""
    items = (
        (alias_keys.get(k, k), str(v))
        for k, v in dsn.items()
        if k != "password" and v is not None
    )
    return frozenset((*items, ("password_fp", pw_fp)))


def _configure_connection(conn: psycopg.Connection) -> None:
    """Configure each new connection created by psycopg_pool.

    Type adapters (numeric→float) are registered here, per-connection, via
    :func:`utils.register_adapters` — deliberately NOT on the process-global
    ``psycopg.adapters``, so importing the db package does not change numeric
    decoding for unrelated psycopg users in the process.

    Prepared statement tuning: Odoo's ORM generates the same query
    shapes repeatedly (SELECT with same columns, UPDATE same fields).
    Auto-preparing after the 2nd execution (instead of default 5)
    skips parse+plan on subsequent calls.  A 500-statement LRU cache
    (instead of default 100) covers the hot ORM paths without bloat.
    PG18's improved plan-cache invalidation makes this safe.

    Per-session GUCs (jit, work_mem) are set via the ``options``
    connection parameter in :func:`_get_or_create_pool` to avoid
    cursor operations in this callback (which runs in pool worker
    threads and can interact badly with pool lifecycle).

    NB: the PostgreSQL minimum-version gate lives in
    :meth:`ConnectionPool.borrow`, not here.  Raising from this callback
    runs inside a pool worker thread: psycopg_pool just logs the error,
    retries with backoff, and the caller eventually gets a generic 30s
    ``PoolTimeout`` — the actionable "upgrade your PostgreSQL" message
    never reaches them.  Checking in ``borrow()`` is a local attribute
    read (no round-trip) and fails fast with the real message.
    """
    # Register Odoo's type adapters on THIS connection (per-connection, not
    # process-global — see utils.register_adapters for the rationale).
    register_adapters(conn)

    # Prepared statement tuning (PG18-optimized)
    conn.prepare_threshold = 2
    conn.prepared_max = 500


def _reset_connection(conn: psycopg.Connection) -> None:
    """Reset connection state when returned to pool.

    psycopg_pool auto-rolls back active transactions before calling
    this. We reset session-level settings that Cursor.__init__ may
    have changed (isolation_level, read_only) and ensure autocommit
    is off for the next user. Using attribute assignment avoids a
    round-trip (unlike ``RESET ALL``).

    Also restore the prepared-statement tuning set by
    :func:`_configure_connection`.  ``Cursor.execute`` may have set
    ``prepare_threshold = None`` in the DDL-fallback path (when
    ``Connection._prepared`` is unavailable) — without this restore the
    next borrower inherits disabled auto-prepare for up to max_lifetime.

    .. warning::
        Arbitrary session-level GUCs set via ``SET x = y`` are NOT
        reset here — they persist on the connection until its
        ``max_lifetime`` (1h) and leak to the next borrower.  Callers
        that need short-lived GUC overrides (``statement_timeout``,
        ``work_mem``, ``search_path``, etc.) MUST use ``SET LOCAL``
        (transaction-scoped) or issue an explicit ``RESET`` before
        releasing the cursor.  Unconditional ``RESET ALL`` here would
        add a round-trip on every pool return and is not justified
        by current callers.
    """
    conn.autocommit = False
    conn.isolation_level = None  # restore server default
    conn.read_only = None  # restore server default
    conn.prepare_threshold = 2  # matches _configure_connection
    conn.prepared_max = 500


class ConnectionPool:
    """Manages per-database psycopg_pool.ConnectionPool instances.

    Each unique DSN (database) gets its own psycopg_pool with:
    - Health checks on borrow (detects dead connections)
    - max_lifetime rotation (recycles connections every hour)
    - Background workers for connection creation
    - Pool statistics via get_stats()

    Connection budget is enforced by ``_pool_sem``, a per-instance bounded
    semaphore sized at ``maxconn``.  Because the R/W and read-only pools
    are two separate ``ConnectionPool`` instances (see ``odoo/db/__init__.py``),
    the PROCESS-WIDE budget is ``2 * maxconn``, not ``maxconn``.

    .. warning::
        The semaphore bounds CHECKED-OUT connections only.  Every per-DSN
        psycopg pool may additionally retain up to ``maxconn`` *idle*
        connections for up to ``max_idle`` (10 min) after a burst, so the
        worst-case server-side footprint of one process is
        ``2 * maxconn * n_databases``, not ``2 * maxconn``.  Single-DB
        deployments are unaffected.  Multi-tenant hosts must size
        PostgreSQL ``max_connections`` accordingly (each per-DSN pool also
        runs ~4 worker threads, and pools are only reaped by
        ``close_database``/``close_all``).
    """

    def __init__(self, maxconn: int = 64, readonly: bool = False, minconn: int = 0):
        # Reject non-positive budgets loudly — the old max(maxconn, 1)
        # silently turned ``db_maxconn=0`` (or a misconfigured gevent
        # override) into a single-slot pool that wedged the whole server
        # under trivial load.
        if maxconn <= 0:
            raise ValueError(f"ConnectionPool maxconn must be >= 1, got {maxconn}")
        # minconn warms that many connections PER per-DSN pool eagerly.  0 keeps
        # the lazy-open default (no idle connections, multi-tenant friendly).
        # It can never exceed the checkout budget, or the pool would open
        # connections it can never hand out.
        if minconn < 0:
            raise ValueError(f"ConnectionPool minconn must be >= 0, got {minconn}")
        if minconn > maxconn:
            raise ValueError(
                f"ConnectionPool minconn ({minconn}) cannot exceed maxconn ({maxconn})"
            )
        self._pools: dict[frozenset, _PsycopgPool] = {}
        self._maxconn = maxconn
        self._minconn = minconn
        self._readonly = readonly
        self._lock = threading.Lock()
        # Per-instance semaphore — gates connections to this pool, not the
        # process.  Name reflects the scope: pool-local, not global.
        self._pool_sem = threading.BoundedSemaphore(self._maxconn)

    def __repr__(self) -> str:
        # NB: get_stats() acquires internal locks — looks expensive, but
        # __repr__ is only evaluated by logging when DEBUG is enabled
        # (Python's logger lazily evaluates %r).  Acceptable at DEBUG.
        total = sum(p.get_stats().get("pool_size", 0) for p in self._pools.values())
        available = sum(
            p.get_stats().get("pool_available", 0) for p in self._pools.values()
        )
        used = total - available
        mode = "read-only" if self._readonly else "read/write"
        return f"ConnectionPool({mode};used={used}/total={total}/limit={self._maxconn};dbs={len(self._pools)})"

    @property
    def readonly(self) -> bool:
        return self._readonly

    def _debug(self, msg: str, *args: object) -> None:
        _logger_conn.debug(("%r " + msg), self, *args)

    def _probe_connectable(self, conninfo: str, kwargs: dict) -> None:
        """Fail fast on a permanently-unreachable target before building a pool.

        psycopg_pool establishes connections in a background worker and retries
        on failure until the borrower's ~30s ``getconn`` budget runs out — even
        when the failure can never succeed (the database does not exist, the
        password is wrong).  A single synchronous probe surfaces those
        permanent errors in milliseconds.  Anything that might be transient
        (server unreachable, still starting up) is swallowed so the pool's
        normal retry can still recover it.

        :raises psycopg.Error: re-raised verbatim for a non-retryable failure,
            so callers see the precise cause (e.g. ``exp_db_exist`` matches
            ``InvalidCatalogName``) instead of an opaque ``PoolError``.
        """
        # Force the probe's own short connect timeout.  _HEALTH_PARAMS already
        # injected connect_timeout=10 into kwargs, so setdefault() would be a
        # silent no-op and the probe would inherit the full 10s — defeating the
        # "surface permanent errors in milliseconds" intent.  Only this
        # throwaway probe is bounded; the real pool connections keep their
        # configured timeout.  Worst case a slow-but-reachable server trips the
        # short timeout, the probe is treated as transient, and we fall through
        # to the pool's normal retry — losing only the optimization, not data.
        probe_kwargs = {**kwargs, "autocommit": True}
        probe_kwargs["connect_timeout"] = _PROBE_CONNECT_TIMEOUT
        try:
            psycopg.connect(conninfo, **probe_kwargs).close()
        except _NON_RETRYABLE_CONNECT_ERRORS:
            # SQLSTATE was already parsed into the precise class — permanent.
            raise
        except psycopg.OperationalError as e:
            # Connection-phase failure: no SQLSTATE, only the FATAL text.
            translated = _translate_connect_error(e)
            if translated is not None:
                raise translated from e
            # Unrecognised / possibly transient — let the pool's retry recover it.
            _logger.debug(
                "Pool pre-flight probe failed (treating as transient)",
                exc_info=True,
            )
        except Exception:
            # Non-connection error (malformed conninfo, etc.) — let the pool
            # surface it the same way it would without the probe.
            _logger.debug(
                "Pool pre-flight probe failed (treating as transient)",
                exc_info=True,
            )

    def _get_or_create_pool(
        self, key: frozenset, connection_info: dict
    ) -> _PsycopgPool:
        """Get an existing pool for this DSN or create a new one."""
        pool = self._pools.get(key)
        if pool is not None and not pool.closed:
            return pool

        # Build conninfo and run the synchronous pre-flight probe BEFORE taking
        # self._lock.  self._lock is process-wide for this ConnectionPool
        # instance and serializes the creation of EVERY per-DSN pool; holding
        # it across the probe's network round-trip lets a single slow or
        # unreachable database stall pool creation for every OTHER database
        # (measured: a 1s probe pushed a sibling database's first connect from
        # 1s to 2s wall).  Both the kwargs build (pure CPU) and the probe
        # (read-only, idempotent) are safe outside the lock; the rare cold-
        # start race where two threads probe the same new key concurrently is
        # harmless — only one wins the create under the double-check below.

        # Build conninfo: extract DSN string if present, rest as kwargs.
        # psycopg_pool passes kwargs to psycopg.connect().
        kwargs = dict(connection_info)
        conninfo = kwargs.pop("dsn", "")
        kwargs["autocommit"] = False

        # Per-session GUCs optimized for Odoo's OLTP workload on PG18.
        # Set via libpq ``options`` so they're applied during connection
        # establishment — no cursor ops needed in the configure callback.
        # - jit=off: compilation overhead (5-50ms) dwarfs execution
        #   savings for Odoo's sub-10ms OLTP queries.
        # - work_mem=16MB: default 4MB causes disk-based sorts for
        #   search_read() with many2one joins + ordering.
        # - idle_session_timeout=15min (PG14+): server-side safety net
        #   for connections that escape pool management.  Set above
        #   pool max_idle (10min) so normal pool recycling takes
        #   precedence; the server only kills truly leaked sessions.
        # NB: these are intentionally hardcoded, not configurable.
        # They are specifically tuned for Odoo's OLTP profile —
        # exposing them in odoo.conf invites misconfiguration with
        # no real upside.  Override via postgresql.conf if needed.
        options = kwargs.get("options", "")
        kwargs["options"] = (
            f"{options} -c jit=off -c work_mem=16MB -c idle_session_timeout=900000"
        ).strip()

        # Fail fast on permanent connect errors (missing DB, bad auth)
        # rather than let psycopg_pool retry them for ~30s.  Cache-miss
        # path only, so the cost (one extra connect for a reachable DB) is
        # paid once per database per process.
        self._probe_connectable(conninfo, kwargs)

        with self._lock:
            # Double-check after acquiring lock: another thread may have built
            # the pool for this key while we were probing.
            pool = self._pools.get(key)
            if pool is not None and not pool.closed:
                return pool

            pool = _PsycopgPool(
                conninfo,
                connection_class=psycopg.Connection,
                kwargs=kwargs,
                min_size=self._minconn,
                max_size=self._maxconn,
                max_lifetime=MAX_LIFETIME,
                max_idle=MAX_IDLE_TIMEOUT,
                reconnect_timeout=15,
                configure=_configure_connection,
                reset=_reset_connection,
                check=_PsycopgPool.check_connection,
                num_workers=3,
                open=True,
            )
            self._pools[key] = pool
            self._debug("Created pool for %s", dict(key))

            # Evict stale-credential siblings: a rotated password yields a NEW
            # key (the password fingerprint in _normalize_dsn_key differs) but
            # leaves the OLD per-DSN pool — its worker threads and idle
            # connections — stranded in self._pools until close_all().  Drop any
            # sibling whose key matches this one on every component EXCEPT the
            # password fingerprint; those connections authenticate with the old
            # password and can only fail now.  A genuinely different host / port
            # / user keeps its own pool (those components ARE part of the key).
            ident = frozenset(t for t in key if t[0] != "password_fp")
            stale_keys = [
                k
                for k in self._pools
                if k != key
                and frozenset(t for t in k if t[0] != "password_fp") == ident
            ]
            # Pop under the lock; close OUTSIDE it — _PsycopgPool.close() joins
            # worker threads and must not block sibling pool creation (the same
            # reason the pre-flight probe runs outside self._lock).
            stale_pools = [self._pools.pop(k) for k in stale_keys]

        for sp in stale_pools:
            try:
                sp.close()
            except Exception:
                _logger.debug("Failed to close stale-credential pool", exc_info=True)
        if stale_pools:
            _logger.info(
                "%r: evicted %d stale-credential pool(s) after key change",
                self,
                len(stale_pools),
            )
        return pool

    def borrow(self, connection_info: dict) -> psycopg.Connection:
        """Borrow a connection from the appropriate per-database pool.

        Acquires a slot from the pool-scoped semaphore first, ensuring the
        total number of checked-out connections across all databases in
        THIS pool instance never exceeds ``maxconn``.  The 30-second
        timeout budget is shared between the semaphore wait and the
        per-database ``getconn()`` call.

        :param dict connection_info: dict of psql connection keywords
        :rtype: psycopg.Connection
        """
        key = _normalize_dsn_key(connection_info)
        pool = self._get_or_create_pool(key, connection_info)

        deadline = monotonic() + _BORROW_TIMEOUT

        if not self._pool_sem.acquire(timeout=_BORROW_TIMEOUT):
            raise PoolError(
                f"Could not acquire connection: pool limit ({self._maxconn}) reached, "
                f"all connections are in use across {len(self._pools)} database(s)"
            )
        try:
            remaining = max(0.1, deadline - monotonic())
            try:
                conn = pool.getconn(timeout=remaining)
            except psycopg.Error as e:
                if isinstance(e, (PoolTimeout, PoolClosed)):
                    # A timeout means the pool couldn't ESTABLISH a
                    # connection in time (the semaphore guarantees checkout
                    # capacity).  Tear the pool down only when it holds no
                    # live connections — i.e. the database is gone or fully
                    # unreachable (e.g. after DB drop), so the next borrow()
                    # builds a fresh pool.  If live connections exist, the
                    # server is reachable but slow; closing them here would
                    # turn a latency blip into a reconnect storm.
                    pool_size = (
                        0
                        if isinstance(e, PoolClosed)
                        else (pool.get_stats().get("pool_size", 0))
                    )
                    if pool_size == 0:
                        with self._lock:
                            if self._pools.get(key) is pool:
                                del self._pools[key]
                        try:
                            pool.close()
                        except Exception:
                            _logger.debug("Failed to close dead pool", exc_info=True)
                    _logger.info("Connection to the database failed: %s", e)
                    raise PoolError(str(e)) from e
                _logger.info("Connection to the database failed: %s", e)
                raise
            except Exception as e:
                raise PoolError(str(e)) from e
            # Post-getconn validation.  Any failure here must do TWO things:
            # return the connection to its psycopg pool (the inner handler) so
            # the pool slot is not leaked, AND release the semaphore (the outer
            # handler).  The earlier version released only the semaphore, so a
            # raise from conn.info access left the psycopg-pool slot checked out
            # forever — exhausting the per-DSN pool over time.
            try:
                # Minimum-version gate: server_version is read from the
                # connection startup packet (client-side, no round-trip).
                # Checked here rather than in _configure_connection so the
                # caller gets the actionable message immediately instead of a
                # generic PoolTimeout after 30s of futile worker retries.
                sv = conn.info.server_version
                if sv < MIN_PG_VERSION * 10000:
                    raise PoolError(
                        f"PostgreSQL {sv // 10000}.{sv % 10000} is below the "
                        f"minimum required {MIN_PG_VERSION}.0. Please upgrade "
                        f"to PostgreSQL {MIN_PG_VERSION} or later."
                    )
                self._debug("Borrow connection backend PID %d", conn.info.backend_pid)
                # Tag the connection with an Odoo-owned back-reference to its
                # per-DSN psycopg pool.  give_back() uses THIS marker — not
                # psycopg_pool's private ``conn._pool`` — both to locate the
                # pool to return to and to decide whether a ``_pool_sem`` permit
                # is held.  Owning the marker makes the semaphore accounting
                # self-contained: it can no longer break if a future
                # psycopg_pool stops tagging connections at checkout (the old
                # design read ``conn._pool`` and would have leaked a permit on
                # every return).  Set last, so it marks only a fully-validated
                # connection we are committed to handing out; a failure above
                # leaves it unset and the inner handler putconn()s the
                # connection with no permit attributed to it.
                conn._odoo_pool = pool
            except BaseException:
                with contextlib.suppress(Exception):
                    pool.putconn(conn)
                raise
        except BaseException:
            self._pool_sem.release()
            raise

        return conn

    def give_back(
        self, connection: psycopg.Connection, keep_in_pool: bool = True
    ) -> None:
        """Return a connection to its pool.

        Releases a slot from the pool-scoped semaphore after returning the
        connection, keeping the per-instance budget accurate.

        :param connection: The connection to return
        :param keep_in_pool: If False, close the connection before returning
            it so the pool discards it (used for template databases).
        """
        # Gate the whole debug block behind the level check: connection.info.dsn
        # is evaluated eagerly as a call argument, and give_back() runs on every
        # cursor close, so accessing it unconditionally costs a DSN build on the
        # hot path even when DEBUG is off.  Mirrors the isEnabledFor guard in
        # Connection.cursor().  (Reading .dsn on a closed connection also raises
        # OperationalError — dead connections are a normal path in here, e.g.
        # rollback after a network drop — hence the .closed branch.)
        if _logger_conn.isEnabledFor(logging.DEBUG):
            if not connection.closed:
                self._debug("Give back connection to %r", connection.info.dsn)
            else:
                self._debug("Give back dead connection %r", connection)
        # Use the Odoo-owned marker set by borrow() — NOT psycopg_pool's private
        # ``conn._pool`` — to recover the per-DSN pool and to decide whether this
        # connection holds a ``_pool_sem`` permit.
        pool = getattr(connection, "_odoo_pool", None)
        if pool is None:
            # Never borrowed (e.g. a manually-created connection), or already
            # given back: it holds no _pool_sem permit, so releasing here would
            # over-increment the bounded semaphore and inflate the budget.  The
            # marker survives a dead/closed connection (it is a plain instance
            # attribute), so this branch is reached only by genuine non-borrowed
            # connections, never by a borrowed-then-dropped one.
            if not connection.closed:
                connection.close()
            return

        # Clear the marker BEFORE releasing so a second give_back() on the same
        # connection takes the no-op branch above instead of releasing a permit
        # twice — a BoundedSemaphore rejects over-release with ValueError, and
        # it would otherwise inflate the budget.
        connection._odoo_pool = None
        try:
            if not keep_in_pool:
                # Close the connection first; the pool detects the closed
                # connection and discards it, creating a replacement if needed.
                with contextlib.suppress(Exception):
                    connection.close()

            try:
                pool.putconn(connection)
            except Exception:
                _logger.debug("Failed to return connection to pool", exc_info=True)
        finally:
            self._pool_sem.release()

    def close_database(self, db_name: str) -> None:
        """Close every per-DSN pool connected to *db_name*.

        Matches on the database component alone, regardless of host, user
        or URI-vs-keyword form — the semantics ``close_db()`` needs when a
        database is dropped or renamed.  ``close_all(dsn)`` requires an
        exact full-DSN match and therefore misses pools created through a
        URI when the caller only knows the database name.
        """
        with self._lock:
            keys = [k for k in self._pools if dict(k).get("database") == db_name]
            pools = [self._pools.pop(k) for k in keys]
        for pool in pools:
            pool.close()
        if pools:
            _logger.info("%r: Closed %d pool(s) for %s", self, len(pools), db_name)

    def close_all(self, dsn: dict | str | None = None) -> None:
        """Close pool(s) — by DSN or all.

        :param dsn: If given, close only the pool matching this DSN.
            If None, close all pools.
        """
        if dsn is not None:
            key = _normalize_dsn_key(dsn)
            with self._lock:
                pool = self._pools.pop(key, None)
            if pool:
                pool.close()
                _logger.info("%r: Closed pool for %s", self, dict(key))
        else:
            with self._lock:
                pools = list(self._pools.values())
                self._pools.clear()
            count = 0
            for pool in pools:
                pool.close()
                count += 1
            if count:
                _logger.info("%r: Closed %d pool(s)", self, count)

    def drain_database(self, db_name: str) -> None:
        """Drain every per-DSN pool connected to *db_name*.

        Name-based matching, like :meth:`close_database` — see there for
        why exact-DSN matching is insufficient.
        """
        with self._lock:
            pools = [
                pool
                for key, pool in self._pools.items()
                if dict(key).get("database") == db_name
            ]
        for pool in pools:
            if not pool.closed:
                pool.drain()
        if pools:
            _logger.debug("%r: Drained %d pool(s) for %s", self, len(pools), db_name)

    def drain(self, dsn: dict | str | None = None) -> None:
        """Drain pool(s) — replace all idle connections with fresh ones.

        After module upgrades, idle connections may hold stale prepared
        statement caches referencing old schema.  ``drain()`` recycles
        them so the next borrow gets a freshly configured connection.

        :param dsn: If given, drain only the pool matching this DSN.
            If None, drain all pools.
        """
        if dsn is not None:
            key = _normalize_dsn_key(dsn)
            pool = self._pools.get(key)
            if pool and not pool.closed:
                pool.drain()
                _logger.debug("%r: Drained pool for %s", self, dict(key))
        else:
            # Snapshot under the lock so a concurrent _get_or_create_pool()
            # or close_all() can't mutate the dict mid-iteration (would
            # raise "dictionary changed size during iteration" otherwise).
            with self._lock:
                pools = list(self._pools.values())
            for pool in pools:
                if not pool.closed:
                    pool.drain()
            if pools:
                _logger.debug("%r: Drained %d pool(s)", self, len(pools))

    def get_stats(self) -> dict[str, dict]:
        """Return pool statistics for all databases.

        Returns a dict keyed by database name with psycopg_pool stats.
        """
        # Snapshot under the lock so a concurrent _get_or_create_pool() or
        # close_all() can't mutate the dict mid-iteration (would raise
        # "dictionary changed size during iteration" otherwise).
        with self._lock:
            snapshot = list(self._pools.items())
        stats = {}
        for key, pool in snapshot:
            db_name = dict(key).get("database", "unknown")
            stats[db_name] = pool.get_stats()
        return stats


class Connection:
    """A lightweight instance of a connection to postgres"""

    __slots__ = ("__dbname", "__dsn", "__pool")

    def __init__(self, pool: ConnectionPool, dbname: str, dsn: dict):
        self.__dbname = dbname
        self.__dsn = dsn
        self.__pool = pool

    @property
    def dsn(self) -> dict:
        """Connection parameters with the password removed (safe to log).

        A URI/conninfo connection stores its secret *inside* the ``dsn``
        string value, not under a ``password`` key, so a bare
        ``pop("password")`` leaks it whenever this dict is logged — e.g. by
        ``cursor()`` at DEBUG, reachable in production via ``log_db`` URIs
        (``logutils``).  Expand the conninfo string into discrete components
        first — the same treatment :func:`_normalize_dsn_key` and psycopg's
        own ``info.dsn`` apply — then drop the password.  Explicit keywords
        win over URI components, matching psycopg's precedence.
        """
        dsn = dict(self.__dsn)
        raw = dsn.pop("dsn", None)
        if raw:
            dsn = {**conninfo_to_dict(raw), **dsn}
        dsn.pop("password", None)
        return dsn

    @property
    def dbname(self) -> str:
        return self.__dbname

    def cursor(self) -> Cursor:
        """Create a new cursor for this connection.

        Note: Import is done here to avoid circular imports.
        """
        from .cursor import Cursor

        # The dsn property builds a sanitized dict copy — only pay for it
        # when DEBUG is actually enabled (cursor creation is per-request).
        if _logger.isEnabledFor(logging.DEBUG):
            _logger.debug("create cursor to %r", self.dsn)
        return Cursor(self.__pool, self.__dbname, self.__dsn)
