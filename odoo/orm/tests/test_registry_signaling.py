"""Regression tests for registry signaling monotonicity and guards.

Tier-2 suite: real ``import odoo``, stub cursors, no database.

Covers the July 2026 audit fixes on ``odoo.orm.runtime.registry``:

* ``check_signaling`` compares sequences **strictly monotonically**: a db read
  *ahead* of the local sequence triggers the reload / cache-clear path, while a
  db read *behind* it (a lagging replica, read through the readonly cursor,
  racing the optimistic local bump in ``signal_changes``) is ignored — no
  reload, no cache clear, and the stored sequences are never regressed;
* ``check_signaling`` adopts a registry another thread already rebuilt and
  published in ``Registry.registries`` instead of rebuilding again;
* ``clear_cache`` validates every cache name up front and raises a ``ValueError``
  listing the valid names (instead of a mid-loop ``KeyError``);
* ``Registry.new`` failure cleanup uses the membership-guarded ``delete`` so a
  nested ``Registry.new`` that already removed the LRU entry cannot mask the
  original exception with a ``KeyError``;
* ``Registry(db_name)`` returns an already-ready registry without taking the
  class-global lock (cross-database fast path), while a not-ready (in-flight)
  registry still goes through the locked path.

And the follow-up audit round on the same file:

* whenever the registry sequence advanced (rebuild AND adopt branches),
  ``check_signaling`` discards the checked-out cursor's cached statement plans
  (``discard_cached_plans``) — the pool drain only recycles *idle* connections,
  so without this the borrowed request cursor keeps stale auto-prepared plans
  and the next re-execution fails with the non-retryable 0A000 "cached plan
  must not change result type";
* the cache-sequence check runs on whichever registry the reload branch
  produced — in particular an *adopted* registry whose ormcaches went stale
  after it was published still gets them cleared;
* the dead-DB cleanup keys on whether ``check_signaling`` opened the cursor
  itself (captured before the ``with`` resolves the cursor), so a mid-query
  connection death on a self-opened cursor evicts the stale registry while a
  caller-provided cursor's failure never does;
* ``get_sequences`` zips strictly, turning any future drift between
  ``_SIGNALING_TABLES`` and ``_CACHES_BY_KEY`` into an immediate error;
* ``setup_signaling`` creates the signaling tables with ``IF NOT EXISTS``
  (fresh-DB cross-process race) and only seeds tables it found missing.
"""

import threading

import psycopg
import pytest

import odoo.db
from odoo.orm.runtime import registry as registry_module
from odoo.orm.runtime.registry import (
    _CACHES_BY_KEY,
    _SIGNALING_TABLES,
    Registry,
    _RegistryCaches,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(db_name, registry_sequence, cache_sequence, *, ready=True):
    """Build a minimal Registry instance without touching a database."""
    reg = object.__new__(Registry)
    reg.db_name = db_name
    reg.ready = ready
    reg.registry_sequence = registry_sequence
    reg.cache_sequences = dict.fromkeys(_CACHES_BY_KEY, cache_sequence)
    reg._caches = _RegistryCaches()
    reg._invalidation_flags = threading.local()
    return reg


class _SeqCursor:
    """Stub cursor: ``get_sequences()`` reads canned signaling values."""

    def __init__(self, registry_sequence, cache_sequences):
        self._row = (
            registry_sequence,
            *(cache_sequences[name] for name in _CACHES_BY_KEY),
        )
        self.plans_discarded = 0

    def execute(self, query, params=None, **kwargs):
        pass

    def fetchone(self):
        return self._row

    def discard_cached_plans(self):
        self.plans_discarded += 1


def _fail(what):
    def boom(*args, **kwargs):
        raise AssertionError(f"{what} must not be called")

    return boom


def _db_caches(value, **overrides):
    caches = dict.fromkeys(_CACHES_BY_KEY, value)
    caches.update(overrides)
    return caches


# ---------------------------------------------------------------------------
# check_signaling — registry sequence
# ---------------------------------------------------------------------------


def test_reload_when_db_registry_sequence_ahead(monkeypatch):
    """db > local: the reload path runs (drain + Registry.new)."""
    reg = _make_registry("_sig_ahead_db", 5, 3)
    rebuilt = _make_registry("_sig_ahead_db", 6, 4)
    calls = []
    monkeypatch.setattr(
        odoo.db, "drain_db", lambda db_name: calls.append(("drain", db_name))
    )

    def fake_new(cls, db_name):
        calls.append(("new", db_name))
        return rebuilt

    monkeypatch.setattr(Registry, "new", classmethod(fake_new))

    cur = _SeqCursor(6, _db_caches(3))
    result = reg.check_signaling(cur)

    assert result is rebuilt
    assert calls == [("drain", "_sig_ahead_db"), ("new", "_sig_ahead_db")]
    # drain_db only recycles idle pooled connections; the cursor used for the
    # check is checked out and must have its stale plans discarded explicitly.
    assert cur.plans_discarded == 1


def test_no_reload_when_db_registry_sequence_behind(monkeypatch):
    """db < local (replica lag): no reload, local sequence and caches kept."""
    reg = _make_registry("_sig_lag_db", 7, 5)
    reg._caches.lrus["default"]["k"] = "v"
    monkeypatch.setattr(odoo.db, "drain_db", _fail("drain_db"))
    monkeypatch.setattr(Registry, "new", classmethod(_fail("Registry.new")))

    cur = _SeqCursor(5, _db_caches(4))
    result = reg.check_signaling(cur)

    assert result is reg
    assert reg.registry_sequence == 7  # kept, not regressed
    assert reg.cache_sequences == dict.fromkeys(_CACHES_BY_KEY, 5)
    assert reg._caches.lrus["default"]["k"] == "v"  # nothing cleared
    assert cur.plans_discarded == 0  # no schema change: plans are fine


def test_adopt_registry_published_by_other_thread(monkeypatch):
    """A newer registry already in ``registries`` is adopted, not rebuilt."""
    name = "_sig_adopt_db"
    stale = _make_registry(name, 5, 3)
    published = _make_registry(name, 6, 4)
    Registry.registries[name] = published
    try:
        monkeypatch.setattr(odoo.db, "drain_db", _fail("drain_db"))
        monkeypatch.setattr(Registry, "new", classmethod(_fail("Registry.new")))

        cur = _SeqCursor(6, _db_caches(4))
        result = stale.check_signaling(cur)

        assert result is published
        # the adopt branch drains nothing on this thread, so the checked-out
        # cursor's stale plans must still be discarded here.
        assert cur.plans_discarded == 1
    finally:
        Registry.registries.pop(name, None)


def test_no_adopt_when_published_registry_too_old(monkeypatch):
    """A published registry older than the db read still forces a rebuild."""
    name = "_sig_noadopt_db"
    stale = _make_registry(name, 5, 3)
    published = _make_registry(name, 5, 3)  # not >= db value (6)
    Registry.registries[name] = published
    rebuilt = _make_registry(name, 6, 4)
    calls = []
    try:
        monkeypatch.setattr(odoo.db, "drain_db", lambda db_name: None)

        def fake_new(cls, db_name):
            calls.append(db_name)
            return rebuilt

        monkeypatch.setattr(Registry, "new", classmethod(fake_new))

        cur = _SeqCursor(6, _db_caches(4))
        result = stale.check_signaling(cur)

        assert result is rebuilt
        assert calls == [name]
        assert cur.plans_discarded == 1
    finally:
        Registry.registries.pop(name, None)


# ---------------------------------------------------------------------------
# check_signaling — cache sequences
# ---------------------------------------------------------------------------


def test_cache_cleared_when_db_cache_sequence_ahead():
    """db > local for one cache: its group is cleared, sequence advanced."""
    reg = _make_registry("_sig_cache_db", 5, 3)
    reg._caches.lrus["assets"]["a"] = 1
    reg._caches.lrus["templates.cached_values"]["t"] = 1
    reg._caches.lrus["default"]["d"] = 1

    result = reg.check_signaling(_SeqCursor(5, _db_caches(3, assets=4)))

    assert result is reg
    assert reg.cache_sequences["assets"] == 4
    # the "assets" group = ("assets", "templates.cached_values")
    assert "a" not in reg._caches.lrus["assets"]
    assert "t" not in reg._caches.lrus["templates.cached_values"]
    # untouched group keeps its entries and sequence
    assert reg._caches.lrus["default"]["d"] == 1
    assert reg.cache_sequences["default"] == 3


def test_cache_kept_when_db_cache_sequence_behind():
    """db < local (replica lag): no clear, stored sequence not regressed."""
    reg = _make_registry("_sig_cache_lag_db", 5, 6)
    reg._caches.lrus["assets"]["a"] = 1

    result = reg.check_signaling(_SeqCursor(5, _db_caches(4)))

    assert result is reg
    assert reg.cache_sequences == dict.fromkeys(_CACHES_BY_KEY, 6)
    assert reg._caches.lrus["assets"]["a"] == 1


def test_adopted_registry_with_lagging_cache_sequences_is_invalidated(monkeypatch):
    """The cache-sequence check runs on an ADOPTED registry too.

    The published registry is new enough on the registry sequence (6 >= 6) but
    its cache sequences (4) lag the db read (5): its ormcaches went stale after
    the other thread rebuilt it.  Adoption must not skip the cache check, or
    the stale entries get served for the whole request.
    """
    name = "_sig_adopt_stale_cache_db"
    stale = _make_registry(name, 5, 3)
    published = _make_registry(name, 6, 4)
    published._caches.lrus["assets"]["stale_key"] = "stale_value"
    Registry.registries[name] = published
    try:
        monkeypatch.setattr(odoo.db, "drain_db", _fail("drain_db"))
        monkeypatch.setattr(Registry, "new", classmethod(_fail("Registry.new")))

        cur = _SeqCursor(6, _db_caches(5))
        result = stale.check_signaling(cur)

        assert result is published
        assert "stale_key" not in published._caches.lrus["assets"]
        assert published.cache_sequences == dict.fromkeys(_CACHES_BY_KEY, 5)
        assert cur.plans_discarded == 1
    finally:
        Registry.registries.pop(name, None)


def test_cache_check_is_noop_on_freshly_rebuilt_registry(monkeypatch):
    """After a rebuild the cache check must not clear the fresh registry.

    ``Registry.new`` -> ``setup_signaling`` seeds the rebuilt registry's cache
    sequences from a DB read at least as new as this check's; the (now
    unconditional) cache-sequence loop is monotonic, so it leaves the fresh
    caches and sequences alone.
    """
    reg = _make_registry("_sig_rebuild_fresh_db", 5, 3)
    rebuilt = _make_registry("_sig_rebuild_fresh_db", 6, 4)
    rebuilt._caches.lrus["assets"]["fresh"] = 1
    monkeypatch.setattr(odoo.db, "drain_db", lambda db_name: None)
    monkeypatch.setattr(Registry, "new", classmethod(lambda cls, db_name: rebuilt))

    result = reg.check_signaling(_SeqCursor(6, _db_caches(4)))

    assert result is rebuilt
    assert rebuilt._caches.lrus["assets"]["fresh"] == 1  # not cleared
    assert rebuilt.cache_sequences == dict.fromkeys(_CACHES_BY_KEY, 4)


# ---------------------------------------------------------------------------
# check_signaling — dead-DB cleanup (own vs caller-provided cursor)
# ---------------------------------------------------------------------------


class _DyingCursor:
    """Cursor that opens fine but dies on first execute (pooled dead conn)."""

    def execute(self, query, params=None, **kwargs):
        raise psycopg.OperationalError("server closed the connection unexpectedly")

    def close(self):
        pass


def test_dead_db_mid_query_on_own_cursor_deletes_registry(monkeypatch):
    """Self-opened cursor dying mid-query evicts the stale registry.

    ``cr is None`` must mean "we opened the cursor ourselves", captured BEFORE
    the ``with`` resolves the cursor — historically the ``as cr`` rebinding
    made the guard mean "opening failed", so a pooled connection dying on the
    first query left the stale registry cached (repeated hangs).
    """
    name = "_sig_dead_mid_query_db"
    reg = _make_registry(name, 5, 3)
    Registry.registries[name] = reg
    monkeypatch.setattr(Registry, "cursor", lambda self, readonly=False: _DyingCursor())
    deleted = []
    monkeypatch.setattr(
        Registry, "delete", classmethod(lambda cls, db_name: deleted.append(db_name))
    )
    try:
        with pytest.raises(psycopg.OperationalError):
            reg.check_signaling()  # cr=None: self-opened cursor
        assert deleted == [name]
    finally:
        Registry.registries.pop(name, None)


def test_dead_db_at_open_deletes_registry(monkeypatch):
    """Control: failure while OPENING the self-opened cursor also deletes."""
    name = "_sig_dead_at_open_db"
    reg = _make_registry(name, 5, 3)
    Registry.registries[name] = reg

    def dying_open(self, readonly=False):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(Registry, "cursor", dying_open)
    deleted = []
    monkeypatch.setattr(
        Registry, "delete", classmethod(lambda cls, db_name: deleted.append(db_name))
    )
    try:
        with pytest.raises(psycopg.OperationalError):
            reg.check_signaling()
        assert deleted == [name]
    finally:
        Registry.registries.pop(name, None)


def test_dead_caller_cursor_keeps_registry(monkeypatch):
    """A caller-provided cursor's failure never evicts the registry.

    The caller's transaction dying mid-request is not proof the database is
    gone; deleting here would force a full reload on the next request.
    """
    name = "_sig_dead_caller_cr_db"
    reg = _make_registry(name, 5, 3)
    Registry.registries[name] = reg
    monkeypatch.setattr(Registry, "delete", classmethod(_fail("Registry.delete")))
    try:
        with pytest.raises(psycopg.OperationalError):
            reg.check_signaling(_DyingCursor())
    finally:
        Registry.registries.pop(name, None)


# ---------------------------------------------------------------------------
# get_sequences — strict row shape
# ---------------------------------------------------------------------------


def test_get_sequences_rejects_row_length_drift():
    """A row not matching ``_CACHES_BY_KEY`` raises instead of dropping keys.

    The SELECT is generated from ``_SIGNALING_TABLES``; if that constant ever
    drifts from ``_CACHES_BY_KEY`` the strict zip must fail immediately rather
    than silently losing a cache group's sequence.
    """

    class _ShortRowCursor:
        def execute(self, query, params=None, **kwargs):
            pass

        def fetchone(self):
            return (1, *([1] * (len(_CACHES_BY_KEY) - 1)))

    reg = _make_registry("_seq_strict_db", 1, 1)
    with pytest.raises(ValueError):
        reg.get_sequences(_ShortRowCursor())


# ---------------------------------------------------------------------------
# setup_signaling — fresh-DB cross-process race
# ---------------------------------------------------------------------------


class _SetupCursor:
    """Records executed statements; answers ``get_sequences``' one SELECT."""

    def __init__(self):
        self.queries = []
        self._row = (1, *([1] * len(_CACHES_BY_KEY)))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params=None, **kwargs):
        self.queries.append(query.code if hasattr(query, "code") else str(query))

    def fetchone(self):
        return self._row


def _run_setup_signaling(monkeypatch, existing_tables):
    reg = _make_registry("_sig_setup_db", -1, -1)
    cur = _SetupCursor()
    monkeypatch.setattr(Registry, "cursor", lambda self, readonly=False: cur)
    monkeypatch.setattr(
        registry_module.sql, "existing_tables", lambda cr, names: existing_tables
    )
    reg.setup_signaling()
    return reg, cur


def test_setup_signaling_creates_tables_if_not_exists(monkeypatch):
    """On a fresh DB every CREATE carries IF NOT EXISTS and is seeded once.

    Two workers racing ``setup_signaling`` on a database whose template lacks
    the tables both pass the ``existing_tables`` pre-check; without the guard
    the loser's CREATE raises DuplicateTable and its registry build fails.
    """
    reg, cur = _run_setup_signaling(monkeypatch, existing_tables=())

    creates = [q for q in cur.queries if q.startswith("CREATE")]
    inserts = [q for q in cur.queries if q.startswith("INSERT")]
    assert len(creates) == len(_SIGNALING_TABLES)
    assert all(q.startswith("CREATE TABLE IF NOT EXISTS") for q in creates)
    assert len(inserts) == len(_SIGNALING_TABLES)
    # baseline sequences captured from the same transaction's read-back
    assert reg.registry_sequence == 1
    assert reg.cache_sequences == dict.fromkeys(_CACHES_BY_KEY, 1)


def test_setup_signaling_does_not_reseed_existing_tables(monkeypatch):
    """Existing tables are neither re-created nor re-seeded.

    Re-seeding on every registry build would bump ``max(id)`` and signal a
    fake registry/cache change to every other worker.
    """
    reg, cur = _run_setup_signaling(
        monkeypatch, existing_tables=tuple(_SIGNALING_TABLES)
    )

    assert not [q for q in cur.queries if q.startswith(("CREATE", "INSERT"))]
    assert reg.registry_sequence == 1


def test_setup_signaling_seeds_only_missing_tables(monkeypatch):
    """A partially-provisioned DB only gets its missing tables created."""
    missing = _SIGNALING_TABLES[0]
    _reg, cur = _run_setup_signaling(
        monkeypatch, existing_tables=tuple(_SIGNALING_TABLES[1:])
    )

    creates = [q for q in cur.queries if q.startswith("CREATE")]
    inserts = [q for q in cur.queries if q.startswith("INSERT")]
    assert len(creates) == 1
    assert len(inserts) == 1
    assert missing in creates[0] and missing in inserts[0]


# ---------------------------------------------------------------------------
# clear_cache validation
# ---------------------------------------------------------------------------


def test_clear_cache_unknown_name_raises_listing_valid_names():
    reg = _make_registry("_cc_db", 1, 1)
    reg._caches.lrus["assets"]["a"] = 1

    with pytest.raises(ValueError) as excinfo:
        reg.clear_cache("assets", "bogus")

    message = str(excinfo.value)
    assert "bogus" in message
    for known in _CACHES_BY_KEY:
        assert known in message
    # validation is up-front: the valid name before the bad one cleared nothing
    assert reg._caches.lrus["assets"]["a"] == 1
    assert not reg.cache_invalidated


def test_clear_cache_rejects_dotted_subcache_name():
    reg = _make_registry("_cc_dotted_db", 1, 1)
    with pytest.raises(ValueError, match=r"templates\.cached_values"):
        reg.clear_cache("templates.cached_values")


def test_clear_cache_known_name_still_works():
    reg = _make_registry("_cc_ok_db", 1, 1)
    reg._caches.lrus["assets"]["a"] = 1

    reg.clear_cache("assets")

    assert "a" not in reg._caches.lrus["assets"]
    assert reg.cache_invalidated == {"assets"}


# ---------------------------------------------------------------------------
# Registry.new failure cleanup
# ---------------------------------------------------------------------------


def test_new_failure_cleanup_survives_nested_delete(monkeypatch):
    """The original exception propagates even if the LRU key is already gone.

    Simulates the uninstall-reload path where a nested ``Registry.new`` failed
    and removed ``registries[db_name]`` on its way out; the outer cleanup must
    not raise ``KeyError`` (which would mask the real error, leaving it only in
    ``__context__``).
    """
    name = "_new_cleanup_db"

    def fake_init(self, db_name):
        self.db_name = db_name

    def fake_setup_signaling(self):
        # nested Registry.new already deleted the key before re-raising
        Registry.registries.pop(self.db_name, None)
        raise RuntimeError("boom")

    monkeypatch.setattr(Registry, "init", fake_init)
    monkeypatch.setattr(Registry, "setup_signaling", fake_setup_signaling)
    try:
        with pytest.raises(RuntimeError, match="boom"):
            Registry.new(name)
    finally:
        Registry.registries.pop(name, None)
    assert name not in Registry.registries


# ---------------------------------------------------------------------------
# Registry.__new__ fast path
# ---------------------------------------------------------------------------


class _ExplodingLock:
    def __enter__(self):
        raise AssertionError("class lock must not be taken on the fast path")

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def test_registry_lookup_of_ready_registry_is_lock_free(monkeypatch):
    name = "_fastpath_db"
    ready_reg = _make_registry(name, 1, 1)
    Registry.registries[name] = ready_reg
    try:
        monkeypatch.setattr(Registry, "_lock", _ExplodingLock())
        assert Registry(name) is ready_reg
    finally:
        Registry.registries.pop(name, None)


def test_registry_lookup_of_inflight_registry_takes_the_lock(monkeypatch):
    name = "_fastpath_notready_db"
    building = _make_registry(name, 1, 1, ready=False)
    Registry.registries[name] = building
    real_lock = threading.RLock()
    acquired = []

    class _RecordingLock:
        def __enter__(self):
            acquired.append(True)
            return real_lock.__enter__()

        def __exit__(self, exc_type, exc_value, traceback):
            return real_lock.__exit__(exc_type, exc_value, traceback)

    monkeypatch.setattr(Registry, "_lock", _RecordingLock())
    try:
        assert Registry(name) is building
        assert acquired, "not-ready registry must be resolved under the lock"
    finally:
        Registry.registries.pop(name, None)


def test_registry_empty_db_name_rejected():
    with pytest.raises(ValueError, match="Missing database name"):
        Registry("")
