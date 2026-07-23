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
"""

import threading

import pytest

import odoo.db
from odoo.orm.runtime.registry import (
    _CACHES_BY_KEY,
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

    def execute(self, query, params=None, **kwargs):
        pass

    def fetchone(self):
        return self._row


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

    result = reg.check_signaling(_SeqCursor(6, _db_caches(3)))

    assert result is rebuilt
    assert calls == [("drain", "_sig_ahead_db"), ("new", "_sig_ahead_db")]


def test_no_reload_when_db_registry_sequence_behind(monkeypatch):
    """db < local (replica lag): no reload, local sequence and caches kept."""
    reg = _make_registry("_sig_lag_db", 7, 5)
    reg._caches.lrus["default"]["k"] = "v"
    monkeypatch.setattr(odoo.db, "drain_db", _fail("drain_db"))
    monkeypatch.setattr(Registry, "new", classmethod(_fail("Registry.new")))

    result = reg.check_signaling(_SeqCursor(5, _db_caches(4)))

    assert result is reg
    assert reg.registry_sequence == 7  # kept, not regressed
    assert reg.cache_sequences == dict.fromkeys(_CACHES_BY_KEY, 5)
    assert reg._caches.lrus["default"]["k"] == "v"  # nothing cleared


def test_adopt_registry_published_by_other_thread(monkeypatch):
    """A newer registry already in ``registries`` is adopted, not rebuilt."""
    name = "_sig_adopt_db"
    stale = _make_registry(name, 5, 3)
    published = _make_registry(name, 6, 4)
    Registry.registries[name] = published
    try:
        monkeypatch.setattr(odoo.db, "drain_db", _fail("drain_db"))
        monkeypatch.setattr(Registry, "new", classmethod(_fail("Registry.new")))

        result = stale.check_signaling(_SeqCursor(6, _db_caches(4)))

        assert result is published
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

        result = stale.check_signaling(_SeqCursor(6, _db_caches(4)))

        assert result is rebuilt
        assert calls == [name]
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
