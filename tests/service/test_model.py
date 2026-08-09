"""Pure-pytest tests for ``odoo.service.model``.

Covers the mockable, database-free portions of the service layer:
  - ``Params.__str__()`` — deterministic RPC-log rendering
  - ``get_public_method()`` — RPC access-control gate
  - ``_force_lazy_values()`` — recursive lazy-value forcing
  - ``retrying()`` — PostgreSQL serialization-retry loop
  - ``call_kw()`` — result shaping and argument validation
  - ``execute_cr()`` — the composition of all of the above
  - ``dispatch()`` — pre-registry argument and database validation

``call_kw`` and ``execute_cr`` were long listed here as needing a live
Environment.  They don't: ``get_public_method``, ``api.Environment`` and
``retrying`` are the only collaborators and all three are patchable.  The
assumption was load-bearing — while it stood, nothing verified that
``execute_cr`` forces lazy values, so deleting that call left every test in
this file green (including the eighteen written to protect the behaviour).

Run with::

    python -m pytest tests/service/ -v
"""

import threading
from contextlib import suppress
from unittest.mock import MagicMock, patch

import psycopg
import psycopg.errors
import pytest

import odoo.http  # noqa: F401 - see below; imported for its side effect
from odoo.db.errors import PG_RETRY_EXCEPTIONS, PG_RETRY_SQLSTATES
from odoo.service.model import Params

# ``odoo.http`` is imported for a SIDE EFFECT, not for use: several tests below
# ``patch("odoo.http")``, which resolves the attribute ``http`` on the ``odoo``
# package and raises ``AttributeError`` if nothing has imported the submodule
# yet.  Nothing in ``odoo.service.model``'s import chain does — the only import
# is the deliberately lazy ``from odoo import http`` INSIDE
# ``odoo.service.transaction.retrying`` (top-level would cycle, see that
# module's docstring), which runs only when a test actually drives ``retrying``.
#
# So those patches used to work purely because ``TestRetrying``'s first two
# tests happened to run first and populate the attribute.  Selecting one test on
# its own — the single most common thing to do while debugging — failed with an
# ``AttributeError`` unrelated to the change under test, and a shuffled
# collection order failed in bulk (7 of 8 random seeds).  Importing it here
# makes the dependency explicit and order-independent.


@pytest.fixture(scope="module")
def mod():
    """Return ``odoo.service.model``, imported once per session."""
    import odoo.service.model as m

    return m


@pytest.fixture(scope="module")
def tx():
    """Return ``odoo.service.transaction`` (home of ``retrying`` + its constants)."""
    import odoo.service.transaction as t

    return t


class _FakeIntegrityError(psycopg.errors.IntegrityError):
    """IntegrityError with a mocked ``diag`` property.

    psycopg's real ``diag`` requires ``_pgresult`` which is only
    available on errors raised by a live connection — unusable in unit tests.
    """

    def __init__(self, table_name: str = "res_partner") -> None:
        Exception.__init__(self, "unique constraint violated")
        self._pgresult = None
        self._diag_mock = MagicMock()
        self._diag_mock.table_name = table_name
        self.sqlstate = "23505"

    @property
    def diag(self):
        return self._diag_mock


@pytest.fixture
def mock_env():
    """Minimal Environment stub for ``retrying()``."""
    e = MagicMock()
    e.cr._closed = False
    e.cr.closed = False
    e.cr.flush = MagicMock()
    e.cr.rollback = MagicMock()
    e.cr.commit = MagicMock()
    # Real cursors carry this from BaseCursor.__init__; retrying() reads it to
    # tell a failed COMMIT from a committed one whose post-commit hook raised.
    e.cr.commit_count = 0
    e.transaction.reset = MagicMock()
    e.registry.reset_changes = MagicMock()
    e.registry.signal_changes = MagicMock()
    e.registry.values.return_value = []
    e._.side_effect = lambda tmpl, *args: tmpl % args if args else tmpl
    return e


class _FakeBaseModel:
    """Minimal BaseModel stand-in that satisfies isinstance() after patching."""

    _name = "test.model"
    _table = "test_model"


class _FakeModel(_FakeBaseModel):
    def public_method(self) -> str:
        return "public"

    def _underscore(self) -> str:
        return "private"

    def api_private_method(self) -> str:
        return "api_private"

    not_callable = "a string attribute"


_FakeModel.api_private_method._api_private = True


class TestGetPublicMethod:
    """get_public_method() enforces RPC access control rules."""

    @pytest.fixture
    def fake_model(self, mod):
        """Return a _FakeModel instance with BaseModel patched in the module."""
        instance = _FakeModel()
        with patch.object(mod, "BaseModel", _FakeBaseModel):
            yield instance

    def test_underscore_prefix_blocked(self, mod, fake_model) -> None:
        from odoo.exceptions import AccessError

        with patch.object(mod, "BaseModel", _FakeBaseModel):
            with pytest.raises(AccessError):
                mod.get_public_method(fake_model, "_underscore")

    def test_unsafe_attribute_blocked(self, mod, fake_model) -> None:
        from odoo.exceptions import AccessError

        with patch.object(mod, "BaseModel", _FakeBaseModel):
            with pytest.raises(AccessError):
                mod.get_public_method(fake_model, "__class__")

    def test_api_private_blocked(self, mod, fake_model) -> None:
        from odoo.exceptions import AccessError

        with patch.object(mod, "BaseModel", _FakeBaseModel):
            with pytest.raises(AccessError):
                mod.get_public_method(fake_model, "api_private_method")

    def test_non_callable_raises_attribute_error(self, mod, fake_model) -> None:
        with patch.object(mod, "BaseModel", _FakeBaseModel):
            with pytest.raises(AttributeError):
                mod.get_public_method(fake_model, "not_callable")

    @pytest.mark.parametrize("name", [123, b"write", None, ("write",), 4.0])
    def test_non_string_method_name_raises_attribute_error(
        self, mod, fake_model, name
    ) -> None:
        """A non-str RPC ``method`` param (reachable via JSON-RPC) must surface as
        AttributeError — the canonical "method not found" signal — not the
        TypeError that ``getattr(cls, name)`` / ``name.startswith`` would raise."""
        with patch.object(mod, "BaseModel", _FakeBaseModel):
            with pytest.raises(AttributeError):
                mod.get_public_method(fake_model, name)

    def test_public_method_returned(self, mod, fake_model) -> None:
        with patch.object(mod, "BaseModel", _FakeBaseModel):
            method = mod.get_public_method(fake_model, "public_method")
        assert callable(method)
        assert method.__name__ == "public_method"

    def test_api_private_blocked_when_defined_in_base_class(self, mod) -> None:
        """_api_private on a BASE class method must still block a subclass instance.

        This is the regression test for the __dict__ optimisation: the MRO loop
        uses mro_cls.__dict__.get(name) which only returns non-None for the class
        that DIRECTLY DEFINES the method.  With the old getattr() approach every
        ancestor class returned non-None via inheritance, causing O(MRO depth)
        redundant checks on the same function object.  With __dict__ the check is
        O(definitions) — but it must still find _api_private even when the
        definition lives deep in the hierarchy.
        """
        from odoo.exceptions import AccessError

        class Base(_FakeBaseModel):
            def deep_private(self) -> str:
                return "from base"

        Base.deep_private._api_private = True

        class Mid(Base):
            pass

        class Leaf(Mid):
            pass

        leaf_instance = Leaf()
        with patch.object(mod, "BaseModel", _FakeBaseModel):
            with pytest.raises(AccessError):
                mod.get_public_method(leaf_instance, "deep_private")


class TestGetPublicMethodCache:
    """The per-class memo (``_PUBLIC_METHOD_CACHE``) must speed resolution up
    WITHOUT changing behaviour or opening an unbounded-growth vector."""

    @pytest.fixture
    def cache(self, mod):
        """Isolate the process-global memo around each test."""
        mod._PUBLIC_METHOD_CACHE.pop(_FakeModel, None)
        yield mod._PUBLIC_METHOD_CACHE
        mod._PUBLIC_METHOD_CACHE.pop(_FakeModel, None)

    def test_success_is_cached_and_stable(self, mod, cache) -> None:
        with patch.object(mod, "BaseModel", _FakeBaseModel):
            first = mod.get_public_method(_FakeModel(), "public_method")
            second = mod.get_public_method(_FakeModel(), "public_method")
        assert first is second
        assert cache[_FakeModel]["public_method"] is first

    def test_rejections_are_not_cached(self, mod, cache) -> None:
        """Private / api-private / missing / non-callable names must never add a
        cache entry: caching them would let an unauthenticated caller grow the
        memo with unbounded distinct fake names (a memory DoS)."""
        from odoo.exceptions import AccessError

        rejects = [
            ("_underscore", AccessError),
            ("api_private_method", AccessError),
            ("not_callable", AttributeError),
            ("missing_xyz", AttributeError),
        ]
        with patch.object(mod, "BaseModel", _FakeBaseModel):
            for name, exc in rejects:
                with pytest.raises(exc):
                    mod.get_public_method(_FakeModel(), name)
        assert cache.get(_FakeModel, {}) == {}

    def test_distinct_classes_do_not_collide(self, mod, cache) -> None:
        """A fresh class object (as a registry reload produces) is a guaranteed
        cache miss — correctness never relies on the old entry being GC'd."""

        class Other(_FakeBaseModel):
            _name = "other.model"

            def public_method(self) -> str:
                return "other"

        with patch.object(mod, "BaseModel", _FakeBaseModel):
            a = mod.get_public_method(_FakeModel(), "public_method")
            b = mod.get_public_method(Other(), "public_method")
        try:
            assert a is not b
            assert cache[_FakeModel]["public_method"] is a
            assert cache[Other]["public_method"] is b
        finally:
            cache.pop(Other, None)

    def test_rebinding_the_method_invalidates_the_entry(self, mod, cache) -> None:
        """The memo must never outlive the binding it memoized.

        Nothing invalidates ``_PUBLIC_METHOD_CACHE``, and the class object is
        unchanged by a rebind, so a stale entry would be served forever.  Not
        hypothetical: ``addons/rpc``'s defaultdict-marshalling test patches
        ``res.users.context_get`` and makes one RPC call; the patched lambda got
        cached, ``patch.stop()`` restored only the class attribute, and every
        later ``execute_kw`` for that method -- in unrelated test classes, for
        the rest of the process -- kept getting the lambda back.  It surfaced as
        three failures far away (``KeyError: 'lang'`` once the empty defaultdict
        was marshalled, ``ctx['tz'] == 0`` straight from ``defaultdict(int)``).
        """
        with patch.object(mod, "BaseModel", _FakeBaseModel):
            original = mod.get_public_method(_FakeModel(), "public_method")
            assert cache[_FakeModel]["public_method"] is original

            def replacement(self) -> str:
                return "replaced"

            with patch.object(_FakeModel, "public_method", replacement):
                got = mod.get_public_method(_FakeModel(), "public_method")
                assert got is replacement

            assert mod.get_public_method(_FakeModel(), "public_method") is original

    def test_rebound_method_is_still_access_checked(self, mod, cache) -> None:
        """Re-resolution must re-run the guards, not merely swap the entry.

        A cached public name later rebound to an ``_api_private`` callable must
        start being rejected.
        """
        from odoo.exceptions import AccessError

        with patch.object(mod, "BaseModel", _FakeBaseModel):
            mod.get_public_method(_FakeModel(), "public_method")

            def sneaky(self) -> str:
                return "nope"

            sneaky._api_private = True
            with patch.object(_FakeModel, "public_method", sneaky):
                with pytest.raises(AccessError):
                    mod.get_public_method(_FakeModel(), "public_method")


def _tracked_lazy():
    """Return ``(lazy_obj, was_forced)`` where ``was_forced()`` reports whether
    the lazy has been evaluated.

    ``lazy(fn)._value`` triggers ``fn`` exactly once, so the closure flag flips
    iff ``_force_lazy_values`` reached and forced the lazy.
    """
    from odoo.tools import lazy

    state = {"forced": False}

    def fn():
        state["forced"] = True
        return 99

    return lazy(fn), (lambda: state["forced"])


class TestForceLazyValues:
    """``_force_lazy_values()`` forces every ``lazy`` reachable in an RPC result,
    across all container shapes, before the cursor closes — and never descends
    into strings/bytes (which would recurse forever) or recordsets.
    """

    def test_top_level_lazy_forced(self, mod) -> None:
        lz, forced = _tracked_lazy()
        mod._force_lazy_values(lz)
        assert forced()

    def test_lazy_in_list_forced(self, mod) -> None:
        lz, forced = _tracked_lazy()
        mod._force_lazy_values([1, lz, 3])
        assert forced()

    def test_lazy_in_nested_list_forced(self, mod) -> None:
        lz, forced = _tracked_lazy()
        mod._force_lazy_values([[lz]])
        assert forced()

    def test_lazy_in_tuple_forced(self, mod) -> None:
        lz, forced = _tracked_lazy()
        mod._force_lazy_values((lz,))
        assert forced()

    def test_lazy_as_dict_value_forced(self, mod) -> None:
        lz, forced = _tracked_lazy()
        mod._force_lazy_values({"key": lz})
        assert forced()

    def test_lazy_dict_key_needs_no_walk(self, mod) -> None:
        lz, forced = _tracked_lazy()
        d = {lz: "value"}
        assert forced()
        mod._force_lazy_values(d)
        assert forced()

    def test_lazy_in_set_forced(self, mod) -> None:
        lz, forced = _tracked_lazy()
        mod._force_lazy_values({lz})
        assert forced()

    def test_lazy_in_frozenset_forced(self, mod) -> None:
        lz, forced = _tracked_lazy()
        mod._force_lazy_values(frozenset({lz}))
        assert forced()

    def test_lazy_in_dict_values_view_forced(self, mod) -> None:
        lz, forced = _tracked_lazy()
        mod._force_lazy_values({"k": lz}.values())
        assert forced()

    def test_deeply_nested_lazy_forced(self, mod) -> None:
        lz, forced = _tracked_lazy()
        mod._force_lazy_values({"a": [{"b": (lz,)}]})
        assert forced()

    def test_top_level_generator_materialized_and_forced(self, mod) -> None:
        lz, forced = _tracked_lazy()
        out = mod._force_lazy_values(x for x in [lz, 2])
        assert isinstance(out, list)
        assert forced()

    def test_nested_generator_forced(self, mod) -> None:
        lz, forced = _tracked_lazy()
        mod._force_lazy_values([(x for x in [lz])])
        assert forced()

    def test_lazy_free_result_returned_unchanged(self, mod) -> None:
        data = [{"id": i, "name": f"r{i}", "active": True, "x": None} for i in range(5)]
        assert mod._force_lazy_values(data) == data

    def test_str_not_descended(self, mod) -> None:
        assert mod._force_lazy_values(["abc"]) == ["abc"]

    def test_str_subclass_does_not_infinite_recurse(self, mod) -> None:
        class MyStr(str):
            __slots__ = ()

        mod._force_lazy_values({"k": MyStr("abcdef")})

    def test_real_lazy_in_odoo_containers_forced(self, mod) -> None:
        """Real ``lazy`` values inside odoo's frozendict / OrderedSet are forced.

        Pins the scalar fast-path: the short-circuit must never swallow a lazy
        held in an exotic container.
        """
        from odoo.tools import OrderedSet, frozendict, lazy

        seen = []
        s1, s2, s3 = (lazy(lambda i=i: seen.append(i)) for i in (1, 2, 3))
        result = [
            frozendict({"a": s1, "b": 2, "c": [s2]}),
            OrderedSet([10, 20]),
            {"k": (s3, "txt", 99)},
        ]
        mod._force_lazy_values(result)
        assert sorted(seen) == [1, 2, 3]

    def test_scalar_heavy_collection_still_forces_lazy(self, mod) -> None:
        lz1, f1 = _tracked_lazy()
        lz2, f2 = _tracked_lazy()
        mod._force_lazy_values([1, 2.0, True, None, "s", b"b", lz1, {"x": 3, "y": lz2}])
        assert f1() and f2()

    def test_cyclic_result_does_not_crash_with_recursionerror(self, mod) -> None:
        """A self-referential result must not blow the stack in the walk.

        ``_force_lazy_in`` recurses per container level, so a cycle (or a
        structure nested past the recursion limit) hits ``RecursionError``.  It
        is a pathological, already-unmarshallable result, but the RPC hot path
        must degrade gracefully — return it for the marshaller to reject — not
        raise a confusing ``RecursionError`` from deep in this traversal.
        """
        cyclic_list: list = [1]
        cyclic_list.append(cyclic_list)
        assert mod._force_lazy_values(cyclic_list) is cyclic_list

        cyclic_dict: dict = {}
        cyclic_dict["self"] = cyclic_dict
        assert mod._force_lazy_values(cyclic_dict) is cyclic_dict

    def test_result_nested_past_recursion_limit_does_not_crash(self, mod) -> None:
        """An acyclic result nested deeper than the recursion limit degrades
        gracefully instead of raising ``RecursionError`` out of dispatch."""
        import sys

        deep: object = "leaf"
        for _ in range(sys.getrecursionlimit() + 500):
            deep = [deep]
        mod._force_lazy_values(deep)


class TestParamsStr:
    """``Params.__str__`` sorts kwargs (for stable logs) and preserves args
    order (positional semantics)."""

    def test_args_preserve_order(self):
        # args in reversed alphabetical order must remain reversed
        p = Params(["z", "a", "m"], {})
        assert str(p) == "'z', 'a', 'm'"

    def test_kwargs_sorted_alphabetically(self):
        p = Params([], {"z_last": 1, "a_first": 2, "m_middle": 3})
        assert str(p) == "a_first=2, m_middle=3, z_last=1"

    def test_mixed_args_and_kwargs(self):
        p = Params(["first", "second"], {"z": 1, "a": 2})
        assert str(p) == "'first', 'second', a=2, z=1"

    def test_deterministic_across_dict_orderings(self):
        # Python dicts preserve insertion order — build two dicts with
        # the same keys in different orders and verify the stringification
        # is identical.
        p1 = Params([], dict.fromkeys(["x", "y", "z"], 0))
        p2 = Params([], dict.fromkeys(["z", "x", "y"], 0))
        assert str(p1) == str(p2)


class TestRetrying:
    """retrying() retry loop — serialization failure handling."""

    def test_success_calls_flush_and_commit(self, mod, mock_env) -> None:
        result = mod.retrying(lambda: 42, mock_env)

        assert result == 42
        mock_env.cr.flush.assert_called_once()
        mock_env.cr.commit.assert_called_once()
        mock_env.registry.signal_changes.assert_called_once()

    def test_closed_cursor_skips_flush_and_commit(self, mod, mock_env) -> None:
        """When cr.closed is True after func(), both flush and commit are skipped.

        ``closed`` is the property that ORs the wrapper-only ``_closed`` with the
        underlying connection's ``_cnx.closed``, so this covers wrapper close,
        connection death, and both.

        ``signal_changes()`` is ALSO skipped on this path: the fork guards
        rollback/reset/commit with ``if not env.cr.closed`` but historically
        left the trailing ``signal_changes()`` ungated, so a transaction whose
        commit was skipped (dead cursor) still broadcast a cache/registry
        invalidation to the whole cluster — a spurious cross-worker reload for a
        change that never committed.  The guard now matches the commit's.
        """
        mock_env.cr._closed = True
        mock_env.cr.closed = True

        result = mod.retrying(lambda: "done", mock_env)

        assert result == "done"
        mock_env.cr.flush.assert_not_called()
        mock_env.cr.commit.assert_not_called()
        mock_env.registry.signal_changes.assert_not_called()

    def test_plain_operational_error_not_retried(self, mod, mock_env) -> None:
        """A bare OperationalError (not a concurrency subtype) re-raises immediately."""
        exc = psycopg.OperationalError("connection reset")
        calls = 0

        def func():
            nonlocal calls
            calls += 1
            raise exc

        with patch("odoo.http") as mock_http:
            mock_http.request = None
            with pytest.raises(psycopg.OperationalError):
                mod.retrying(func, mock_env)

        assert calls == 1

    def test_serialization_failure_retried(self, mod, mock_env) -> None:
        """SerializationFailure triggers a retry."""
        exc = psycopg.errors.SerializationFailure()
        exc.sqlstate = "40001"
        calls = 0

        def func():
            nonlocal calls
            calls += 1
            if calls < 2:
                raise exc
            return "ok"

        with (
            patch("odoo.http") as mock_http,
            patch("odoo.service.transaction.time"),
            patch("odoo.service.transaction.backoff") as mock_backoff,
        ):
            mock_http.request = None
            mock_backoff.delay.return_value = 0.0
            result = mod.retrying(func, mock_env)

        assert result == "ok"
        assert calls == 2

    def test_deadlock_retried(self, mod, mock_env) -> None:
        """DeadlockDetected triggers a retry."""
        exc = psycopg.errors.DeadlockDetected()
        exc.sqlstate = "40P01"
        calls = 0

        def func():
            nonlocal calls
            calls += 1
            if calls < 2:
                raise exc
            return "ok"

        with (
            patch("odoo.http") as mock_http,
            patch("odoo.service.transaction.time"),
            patch("odoo.service.transaction.backoff") as mock_backoff,
        ):
            mock_http.request = None
            mock_backoff.delay.return_value = 0.0
            result = mod.retrying(func, mock_env)

        assert result == "ok"
        assert calls == 2

    def test_lock_not_available_retried(self, mod, mock_env) -> None:
        """LockNotAvailable triggers a retry."""
        exc = psycopg.errors.LockNotAvailable()
        exc.sqlstate = "55P03"
        calls = 0

        def func():
            nonlocal calls
            calls += 1
            if calls < 2:
                raise exc
            return "ok"

        with (
            patch("odoo.http") as mock_http,
            patch("odoo.service.transaction.time"),
            patch("odoo.service.transaction.backoff") as mock_backoff,
        ):
            mock_http.request = None
            mock_backoff.delay.return_value = 0.0
            result = mod.retrying(func, mock_env)

        assert result == "ok"
        assert calls == 2

    def test_max_retries_exhausted_raises(self, mod, mock_env) -> None:
        """After MAX_TRIES_ON_CONCURRENCY_FAILURE, the last exception propagates."""
        exc = psycopg.errors.SerializationFailure()
        exc.sqlstate = "40001"

        def func():
            raise exc

        with (
            patch("odoo.http") as mock_http,
            patch("odoo.service.transaction.time"),
            patch("odoo.service.transaction.backoff") as mock_backoff,
        ):
            mock_http.request = None
            mock_backoff.delay.return_value = 0.0
            with pytest.raises(psycopg.errors.SerializationFailure):
                mod.retrying(func, mock_env)

    def test_sleep_called_between_retries_not_on_last(self, mod, tx, mock_env) -> None:
        """time.sleep is called N-1 times for N attempts (no sleep after last failure)."""
        exc = psycopg.errors.SerializationFailure()
        exc.sqlstate = "40001"
        max_tries = tx.MAX_TRIES_ON_CONCURRENCY_FAILURE

        def func():
            raise exc

        with (
            patch("odoo.http") as mock_http,
            patch("odoo.service.transaction.time") as mock_time,
            patch("odoo.service.transaction.backoff") as mock_backoff,
        ):
            mock_http.request = None
            mock_backoff.delay.return_value = 0.0
            with suppress(psycopg.errors.SerializationFailure):
                mod.retrying(func, mock_env)

        assert mock_time.sleep.call_count == max_tries - 1

    def test_integrity_error_converted_to_validation_error(self, mod, mock_env) -> None:
        """IntegrityError → ValidationError with the model's sql_error_to_message."""
        from odoo.exceptions import ValidationError

        exc = _FakeIntegrityError(table_name="some_table")

        matching_model = MagicMock()
        matching_model._name = "some.model"
        matching_model._table = "some_table"
        matching_model._sql_error_to_message.return_value = "Unique constraint"

        mock_env.registry.values.return_value = [matching_model]
        mock_env.__getitem__ = MagicMock(return_value=matching_model)

        def func():
            raise exc

        with patch("odoo.http") as mock_http:
            mock_http.request = None
            with pytest.raises(
                ValidationError, match="The operation cannot be completed"
            ):
                mod.retrying(func, mock_env)

    def test_integrity_error_with_closed_connection_reraises(
        self, mod, mock_env
    ) -> None:
        """IntegrityError + closed cursor re-raises without ValidationError conversion.

        With ``closed=True`` the inner-except short-circuits at the unusable-cursor
        check (model.py line 241) before ever reaching the IntegrityError-specific
        constraint-name lookup, which would itself need a live connection.
        """
        exc = _FakeIntegrityError()
        mock_env.cr._closed = False
        mock_env.cr.closed = True

        def func():
            raise exc

        with patch("odoo.http") as mock_http:
            mock_http.request = None
            with pytest.raises(_FakeIntegrityError):
                mod.retrying(func, mock_env)

    @pytest.mark.parametrize(
        ("wrapper_closed", "conn_dead"),
        [
            pytest.param(True, False, id="wrapper-explicitly-closed"),
            pytest.param(False, True, id="underlying-connection-dead"),
            pytest.param(True, True, id="both"),
        ],
    )
    def test_closed_cursor_in_inner_except_reraises_immediately(
        self, mod, mock_env, wrapper_closed, conn_dead
    ) -> None:
        """If the cursor is unusable when catching a concurrency error, re-raise without retry.

        Regression: the prior implementation checked ``cr._closed`` (the wrapper-only flag)
        which missed the case where the underlying psycopg connection had died (e.g. after
        DB drop, idle timeout, network partition).  The fix checks ``cr.closed`` (the
        property that ORs wrapper-close with ``_cnx.closed``), so connection death also
        short-circuits the retry loop instead of burning the random-backoff budget on
        a connection that will never recover.
        """
        mock_env.cr._closed = wrapper_closed
        mock_env.cr.closed = wrapper_closed or conn_dead
        exc = psycopg.errors.SerializationFailure()
        exc.sqlstate = "40001"
        calls = 0

        def func():
            nonlocal calls
            calls += 1
            raise exc

        with pytest.raises(psycopg.errors.SerializationFailure):
            mod.retrying(func, mock_env)

        assert calls == 1

    def test_rollback_error_suppressed(self, mod, mock_env) -> None:
        """Errors raised by cr.rollback() during retry are swallowed."""
        exc = psycopg.errors.SerializationFailure()
        exc.sqlstate = "40001"
        mock_env.cr.rollback.side_effect = RuntimeError("rollback failed")
        calls = 0

        def func():
            nonlocal calls
            calls += 1
            if calls < 2:
                raise exc
            return "ok"

        with (
            patch("odoo.http") as mock_http,
            patch("odoo.service.transaction.time"),
            patch("odoo.service.transaction.backoff") as mock_backoff,
        ):
            mock_http.request = None
            mock_backoff.delay.return_value = 0.0
            result = mod.retrying(func, mock_env)

        assert result == "ok"

    def test_outer_except_resets_registry_on_non_retryable_error(
        self, mod, mock_env
    ) -> None:
        """On a non-retryable exception, outer except runs transaction.reset and registry.reset_changes."""
        exc = ValueError("boom")

        def func():
            raise exc

        with pytest.raises(ValueError, match="boom"):
            mod.retrying(func, mock_env)

        mock_env.transaction.reset.assert_called()
        mock_env.registry.reset_changes.assert_called()

    def test_outer_except_skips_reset_when_connection_closed(
        self, mod, mock_env
    ) -> None:
        """When connection is dead, outer except skips transaction.reset."""
        mock_env.cr.closed = True
        exc = ValueError("boom")

        def func():
            raise exc

        with pytest.raises(ValueError, match="boom"):
            mod.retrying(func, mock_env)

        mock_env.transaction.reset.assert_not_called()
        mock_env.registry.reset_changes.assert_not_called()

    def test_commit_time_failure_runs_cleanup_without_retry(
        self, mod, mock_env
    ) -> None:
        """A SerializationFailure raised by commit() (not by the in-loop flush)
        is NOT retried, but transaction.reset()/registry.reset_changes() still
        run and signal_changes() does not."""
        exc = psycopg.errors.SerializationFailure()
        exc.sqlstate = "40001"
        mock_env.cr.commit.side_effect = exc
        calls = 0

        def func():
            nonlocal calls
            calls += 1
            return "ok"

        with patch("odoo.http") as mock_http:
            mock_http.request = None
            with pytest.raises(psycopg.errors.SerializationFailure):
                mod.retrying(func, mock_env)

        assert calls == 1
        mock_env.transaction.reset.assert_called()
        mock_env.registry.reset_changes.assert_called()
        mock_env.registry.signal_changes.assert_not_called()

    def test_commit_time_integrity_error_translated_to_validation_error(
        self, mod, mock_env
    ) -> None:
        """A deferred-constraint IntegrityError that fires at COMMIT gets the
        same friendly ValidationError translation as the in-loop path."""
        from odoo.exceptions import ValidationError

        exc = _FakeIntegrityError(table_name="some_table")
        mock_env.cr.commit.side_effect = exc

        matching_model = MagicMock()
        matching_model._name = "some.model"
        matching_model._table = "some_table"
        matching_model._sql_error_to_message.return_value = "Unique constraint"
        mock_env.registry.values.return_value = [matching_model]
        mock_env.__getitem__ = MagicMock(return_value=matching_model)

        with patch("odoo.http") as mock_http:
            mock_http.request = None
            with pytest.raises(
                ValidationError, match="The operation cannot be completed"
            ):
                mod.retrying(lambda: "ok", mock_env)

        mock_env.transaction.reset.assert_called()
        mock_env.registry.reset_changes.assert_called()

    def test_commit_time_integrity_translation_failure_falls_back_to_raw(
        self, mod, mock_env
    ) -> None:
        """If translating a commit-time IntegrityError itself fails, the raw
        IntegrityError surfaces — the error path never masks one crash with
        another."""
        exc = _FakeIntegrityError(table_name="some_table")
        mock_env.cr.commit.side_effect = exc

        broken_model = MagicMock()
        broken_model._table = "some_table"
        broken_model._sql_error_to_message.side_effect = RuntimeError("dead cursor")
        mock_env.registry.values.return_value = [broken_model]
        mock_env.__getitem__ = MagicMock(return_value=broken_model)

        with patch("odoo.http") as mock_http:
            mock_http.request = None
            with pytest.raises(_FakeIntegrityError):
                mod.retrying(lambda: "ok", mock_env)


class TestIntegrityErrorPicksTheRightModel:
    """The friendly ``ValidationError`` is built from the model whose ``_table``
    matches the failing constraint's — ``registry.models_by_table[table_name]``.

    Every existing test registers exactly ONE model and has ``env[...]`` return
    that same mock regardless of the key, so the lookup could not be wrong:
    confirmed by mutation, flipping the old scan's ``==`` to ``!=`` left the
    suite green.  With several models registered — which is the real shape of a
    registry — the lookup is load-bearing again.

    The fake carried ``registry.values()`` until 2026-08-09, when the linear
    scan over every model became a ``models_by_table`` index on ``Registry``;
    ``values()`` is still populated so the fake stays a faithful registry and a
    reader can see what the index is built from.
    """

    @staticmethod
    def _model(name, table, message):
        m = MagicMock()
        m._name = name
        m._table = table
        m._sql_error_to_message.return_value = message
        return m

    def _run(self, mod, mock_env, failing_table):
        partner = self._model("res.partner", "res_partner", "partner says no")
        invoice = self._model("account.move", "account_move", "invoice says no")
        base = self._model("base", "base", "base says no")
        by_name = {m._name: m for m in (partner, invoice, base)}

        mock_env.registry.values.return_value = [partner, invoice]
        mock_env.registry.models_by_table = {m._table: m for m in (partner, invoice)}
        mock_env.__getitem__ = MagicMock(side_effect=by_name.__getitem__)

        def func():
            raise _FakeIntegrityError(table_name=failing_table)

        with patch("odoo.http") as mock_http:
            mock_http.request = None
            with pytest.raises(Exception) as excinfo:
                mod.retrying(func, mock_env)
        return str(excinfo.value), by_name

    def test_the_matching_model_formats_the_message(self, mod, mock_env):
        message, _ = self._run(mod, mock_env, "account_move")
        assert "invoice says no" in message
        assert "partner says no" not in message

    def test_a_different_constraint_selects_a_different_model(self, mod, mock_env):
        message, _ = self._run(mod, mock_env, "res_partner")
        assert "partner says no" in message
        assert "invoice says no" not in message

    def test_only_the_matching_model_is_asked_to_format(self, mod, mock_env):
        _message, by_name = self._run(mod, mock_env, "account_move")
        by_name["account.move"]._sql_error_to_message.assert_called_once()
        by_name["res.partner"]._sql_error_to_message.assert_not_called()

    def test_an_unknown_table_falls_back_to_base(self, mod, mock_env):
        """A constraint on a table no registered model owns still produces a
        message rather than an ``IndexError`` or a raw driver error."""
        message, _by_name = self._run(mod, mock_env, "some_table_nobody_owns")
        assert "base says no" in message


class TestConcurrencyBackoffSchedule:
    """The retry wait is ``backoff.delay(tryno, base=BASE, cap=MAX)``.

    The cron worker's equivalent schedule IS pinned exactly
    (``[2, 4, 8, 16, 32, 60, 60]`` in ``test_server``), and until 2026-08-08 this
    one deliberately was not.  The previous revision of this class computed its
    own expectation with the same expression the code used
    (``min(2**n, cap)``), which is tautological, and its docstring recorded WHY:
    at ``cap = 2.0`` the growth term is inert, because ``2**tryno`` is already 2
    on the first retry, so every attempt clamped to the cap and the schedule was
    flat-with-jitter.  It concluded that there was "nothing here to catch" and
    pinned the flat behaviour, deferring a real curve to "if the cap is ever
    raised".

    That took the cap as given and the curve as negotiable.  It was the wrong way
    round: what was missing is a *base*, so that the cap binds late instead of
    from attempt 1.  ``BASE_CONCURRENCY_BACKOFF_SECONDS`` supplies it and
    :mod:`odoo.libs.backoff` owns the schedule, so these tests now assert the
    growth curve itself — independently derived, not recomputed from the
    implementation's own expression.
    """

    def _bounds(self, mod, tx, mock_env):
        exc = psycopg.errors.SerializationFailure()
        exc.sqlstate = "40001"
        bounds = []

        def func():
            raise exc

        with (
            patch("odoo.http") as mock_http,
            patch("odoo.service.transaction.time"),
            patch("odoo.service.transaction.backoff") as mock_backoff,
        ):
            mock_http.request = None
            mock_backoff.delay.side_effect = lambda attempt, *, base, cap: (
                bounds.append((0.0, min(base * 2.0 ** (attempt - 1), cap))) or 0.0
            )
            with suppress(psycopg.errors.SerializationFailure):
                mod.retrying(func, mock_env)
        return bounds

    def test_the_bound_doubles_each_attempt_up_to_the_cap(self, mod, tx, mock_env):
        bounds = self._bounds(mod, tx, mock_env)
        assert bounds, "no backoff was computed at all"
        # Written out rather than derived, so a change to the constants has to be
        # acknowledged here.  This is the assertion the old tautological form
        # could not make.
        assert bounds == [(0.0, 0.2), (0.0, 0.4), (0.0, 0.8), (0.0, 1.6)]

    def test_the_schedule_is_not_flat(self, mod, tx, mock_env):
        """The regression this class exists for.

        A cap at or below the first bound collapses the curve to a constant, and
        every previous test here would still pass.
        """
        highs = [hi for _lo, hi in self._bounds(mod, tx, mock_env)]
        assert len(set(highs)) > 1, f"backoff is flat: every retry bounded by {highs}"
        assert highs == sorted(highs) and highs[0] < highs[-1]

    def test_the_backoff_is_jittered_from_zero(self, mod, tx, mock_env):
        """``uniform(0, bound)`` rather than ``sleep(bound)``: without the
        jitter every worker contending on the same row retries in lockstep and
        collides again.  The lower bound must stay 0, not the previous wait."""
        bounds = self._bounds(mod, tx, mock_env)
        assert bounds
        assert all(lo == 0.0 for lo, _hi in bounds)

    def test_no_wait_ever_exceeds_the_cap(self, mod, tx, mock_env):
        """The property the cap exists for: a request retried to exhaustion adds
        at most ``MAX_TRIES - 1`` waits of ``cap`` seconds to its own latency."""
        bounds = self._bounds(mod, tx, mock_env)
        cap = tx.MAX_CONCURRENCY_BACKOFF_SECONDS
        assert all(hi <= cap for _lo, hi in bounds), bounds

    def test_one_wait_per_retry_and_none_after_the_last(self, mod, tx, mock_env):
        """Pairs the bound with the retry it precedes — the count assertion
        elsewhere is on ``time.sleep``, which says nothing about how many bounds
        were computed."""
        bounds = self._bounds(mod, tx, mock_env)
        assert len(bounds) == tx.MAX_TRIES_ON_CONCURRENCY_FAILURE - 1


class TestRetryVocabularyMatchesPostgres:
    """The retry SQLSTATE set and exception-class tuple must stay in sync with
    each other AND with psycopg's own SQLSTATE→class mapping.

    ``retrying()`` recognises a retryable failure via
    ``isinstance(exc, PG_RETRY_EXCEPTIONS)`` and then logs it with
    ``errors.lookup(exc.sqlstate).__name__``.  If the two lists drift — or drift
    from psycopg — a real serialization failure would either silently not retry
    or crash the logging path.  The rest of ``TestRetrying`` uses hand-built mock
    exceptions; these tests pin the vocabulary to psycopg's real mapping so a
    genuine cluster error (verified live: 40001/40P01/55P03) is always handled,
    without needing a database.

    Pinned against ``odoo.db.errors``, which is where the vocabulary is defined.
    Until 2026-08-08 these read it through ``PG_CONCURRENCY_{ERRORS,EXCEPTIONS}_TO_RETRY``,
    two aliases re-exported from ``service.transaction`` — one of which had no
    functional reader at all.  Testing an alias tests the alias.
    """

    def test_every_retry_sqlstate_maps_to_an_exception_in_the_tuple(self) -> None:
        for sqlstate in PG_RETRY_SQLSTATES:
            cls = psycopg.errors.lookup(sqlstate)
            assert issubclass(cls, PG_RETRY_EXCEPTIONS), (
                f"sqlstate {sqlstate!r} maps to {cls.__name__}, which is absent "
                f"from PG_RETRY_EXCEPTIONS — retrying() would not "
                f"retry a real error carrying this sqlstate"
            )

    def test_canonical_concurrency_errors_are_recognised(self) -> None:
        """The three errors a real cluster raises under contention must each be
        an instance of the retry tuple and carry a retryable sqlstate."""
        for name, sqlstate in [
            ("SerializationFailure", "40001"),
            ("DeadlockDetected", "40P01"),
            ("LockNotAvailable", "55P03"),
        ]:
            cls = getattr(psycopg.errors, name)
            assert issubclass(cls, PG_RETRY_EXCEPTIONS), name
            assert sqlstate in PG_RETRY_SQLSTATES, name

    def test_the_addon_facing_aliases_stay_identical_to_the_canonical_names(
        self, tx
    ) -> None:
        """``PG_CONCURRENCY_*_TO_RETRY`` is a supported re-export, not dead weight.

        ``addons/mail`` reads both (``mail_message_schedule``, ``mail_presence``)
        and three ``enterprise`` modules import the exception tuple through
        ``odoo.service.model``, which re-exports it in turn. They must stay the
        *same objects* as ``odoo.db.errors``' names — an alias that drifts into a
        copy would silently stop matching real errors.
        """
        assert tx.PG_CONCURRENCY_EXCEPTIONS_TO_RETRY is PG_RETRY_EXCEPTIONS
        assert tx.PG_CONCURRENCY_ERRORS_TO_RETRY is PG_RETRY_SQLSTATES


class _RecordingParticipant:
    """A :class:`RetryParticipant` that records which hooks fired.

    Replaces four tests that patched ``odoo.http`` and
    ``odoo.http.helpers.rewind_uploaded_files`` to observe the same thing. The
    invariant was never about HTTP: it is that ``on_rollback`` runs on every
    failure path and ``on_retry`` only when a replay will follow. Asserting it
    through the seam states that directly, and keeps working now that
    ``retrying()`` does not import ``odoo.http`` at all.
    """

    def __init__(self):
        self.rollbacks = []
        self.retries = []
        self.suppress = False

    def on_rollback(self, exc):
        self.rollbacks.append(exc)

    def on_retry(self, exc):
        self.retries.append(exc)

    def suppresses_uncommitted_warning(self):
        return self.suppress


@pytest.fixture
def participant(tx, monkeypatch):
    """Install a recording participant for the duration of one test.

    Patched on ``odoo.service.transaction`` (``tx``), not on
    ``odoo.service.model`` (``mod``): the seam is a module global that
    ``retrying`` resolves at call time in its own module.
    """
    recorder = _RecordingParticipant()
    monkeypatch.setattr(tx, "current_retry_participant", lambda: recorder)
    return recorder


class TestRetryParticipantHooks:
    """``on_rollback`` fires on EVERY failure path — transaction-coupled
    transport state must not outlive the rollback — while ``on_retry`` fires
    ONLY when a replay is certain. On the raise paths a replay hook would be
    wasted work, and for HTTP specifically a non-seekable upload would raise
    RuntimeError from the rewind and mask the real error."""

    def test_a_retried_failure_fires_both_hooks(self, mod, mock_env, participant):
        exc = psycopg.errors.SerializationFailure()
        exc.sqlstate = "40001"
        calls = 0

        def func():
            nonlocal calls
            calls += 1
            if calls < 2:
                raise exc
            return "ok"

        with (
            patch("odoo.service.transaction.time"),
            patch("odoo.service.transaction.backoff") as mock_backoff,
        ):
            mock_backoff.delay.return_value = 0.0
            assert mod.retrying(func, mock_env) == "ok"

        assert participant.rollbacks == [exc]
        assert participant.retries == [exc]

    def test_integrity_error_rolls_back_but_never_retries(
        self, mod, mock_env, participant
    ):
        from odoo.exceptions import ValidationError

        exc = _FakeIntegrityError(table_name="some_table")
        matching_model = MagicMock()
        matching_model._name = "some.model"
        matching_model._table = "some_table"
        matching_model._sql_error_to_message.return_value = "Unique constraint"
        mock_env.registry.models_by_table = {"some_table": matching_model}
        mock_env.__getitem__ = MagicMock(return_value=matching_model)

        def func():
            raise exc

        with pytest.raises(ValidationError):
            mod.retrying(func, mock_env)

        assert participant.rollbacks == [exc]
        assert participant.retries == []

    def test_a_non_retryable_operational_error_rolls_back_but_never_retries(
        self, mod, mock_env, participant
    ):
        exc = psycopg.OperationalError("connection reset")
        exc.sqlstate = None

        def func():
            raise exc

        with pytest.raises(psycopg.OperationalError):
            mod.retrying(func, mock_env)

        assert participant.rollbacks == [exc]
        assert participant.retries == []

    def test_exhausting_the_retries_fires_one_fewer_retry_than_rollback(
        self, mod, mock_env, tx, participant
    ):
        """``on_retry`` pairs with a replay: after the LAST failure there is no
        replay, so N attempts give N rollbacks and N-1 retries."""
        exc = psycopg.errors.SerializationFailure()
        exc.sqlstate = "40001"

        def func():
            raise exc

        with (
            patch("odoo.service.transaction.time"),
            patch("odoo.service.transaction.backoff") as mock_backoff,
        ):
            mock_backoff.delay.return_value = 0.0
            with pytest.raises(psycopg.errors.SerializationFailure):
                mod.retrying(func, mock_env)

        assert len(participant.rollbacks) == tx.MAX_TRIES_ON_CONCURRENCY_FAILURE
        assert len(participant.retries) == tx.MAX_TRIES_ON_CONCURRENCY_FAILURE - 1

    def test_no_participant_means_no_hooks_and_no_http_import(
        self, mod, tx, mock_env
    ):
        """The RPC and cron paths install nothing and must still retry.

        They used to opt out implicitly, by ``http.request`` being falsy.
        """
        exc = psycopg.errors.SerializationFailure()
        exc.sqlstate = "40001"
        calls = 0

        def func():
            nonlocal calls
            calls += 1
            if calls < 2:
                raise exc
            return "ok"

        assert tx.current_retry_participant() is None
        with (
            patch("odoo.service.transaction.time"),
            patch("odoo.service.transaction.backoff") as mock_backoff,
        ):
            mock_backoff.delay.return_value = 0.0
            assert mod.retrying(func, mock_env) == "ok"


class TestUncommittedWarningSuppression:
    def test_the_participant_can_suppress_the_warning(
        self, mod, tx, mock_env, participant
    ):
        participant.suppress = True
        mock_env.cr.closed = True
        with patch.object(tx._logger, "warning") as warn:
            mod.retrying(lambda: "done", mock_env)
        warn.assert_not_called()

    def test_otherwise_the_warning_is_emitted(self, mod, tx, mock_env, participant):
        participant.suppress = False
        mock_env.cr.closed = True
        with patch.object(tx._logger, "warning") as warn:
            mod.retrying(lambda: "done", mock_env)
        warn.assert_called_once()


@pytest.fixture
def owns_rpc_model_method(monkeypatch):
    """Declare that this test OWNS ``current_thread().rpc_model_method``.

    ``execute_cr`` stamps the label on whichever thread runs the call, which
    under pytest is the MainThread — so without this it leaks into every later
    test and into the runner's own log records.

    ``monkeypatch`` owns the teardown, which is what ``conftest``'s
    ``_no_global_state_leak`` failure message asks for.  This was a hand-rolled
    save/restore, byte-identical to a second copy in ``test_server.py``; both
    are gone.  Deliberately opt-in, never ``autouse``: an ``autouse`` restore
    disarms the guard for every test in the file, including the ones leaking by
    accident (which is exactly what had happened in ``test_server.py``).
    """
    monkeypatch.setattr(
        threading.current_thread(), "rpc_model_method", None, raising=False
    )


class TestExecuteCr:
    """``execute_cr`` is the composition step: reset the cursor, build the env,
    resolve the model, run through ``retrying``, force lazies, return.

    Every piece it wires together is tested in isolation above — and that was
    exactly the gap.  Nothing asserted that ``execute_cr`` actually CALLS them,
    so the wiring itself was unpinned: verified by mutation, deleting the
    ``result = _force_lazy_values(result)`` line entirely left the whole
    760-test suite green, including the eighteen ``TestForceLazyValues`` tests
    written to protect that very behaviour.  A lazy escaping to the marshaller
    after the cursor closes is the failure those tests exist to prevent, and it
    could have shipped with all of them passing.

    The module docstring listed ``execute_cr`` under "NOT covered here (require
    a live cursor / registry / ORM)".  It doesn't: ``api.Environment`` and
    ``retrying`` are the only collaborators, and both are patchable — the same
    realisation that let ``TestCallKw`` be written.
    """

    def _env(self, recs):
        env = MagicMock()
        env.get.return_value = recs
        return env

    def _run(self, mod, *, recs=None, retrying_returns="ok"):
        """Drive ``execute_cr`` with ``api.Environment`` and ``retrying`` stubbed."""
        cr = MagicMock()
        env = self._env(MagicMock() if recs is None else recs)
        with (
            patch.object(mod.api, "Environment", return_value=env),
            patch.object(mod, "retrying", return_value=retrying_returns) as retry,
        ):
            result = mod.execute_cr(cr, 7, "res.partner", "read", [[1]], {})
        return result, cr, env, retry

    def test_cursor_is_reset_before_the_call(self, mod, owns_rpc_model_method):
        """A retried request reuses the cursor; stale caches from the previous
        attempt must not survive into this one."""
        _result, cr, _env, _retry = self._run(mod)
        cr.reset.assert_called_once_with()

    def test_result_is_passed_through_force_lazy_values(
        self, mod, owns_rpc_model_method
    ):
        """The regression the mutation exposed: the forcing must actually happen."""
        cr = MagicMock()
        env = self._env(MagicMock())
        sentinel = object()
        with (
            patch.object(mod.api, "Environment", return_value=env),
            patch.object(mod, "retrying", return_value="raw"),
            patch.object(mod, "_force_lazy_values", return_value=sentinel) as forced,
        ):
            out = mod.execute_cr(cr, 7, "res.partner", "read", [[1]], {})
        forced.assert_called_once_with("raw")
        assert out is sentinel, "execute_cr returned the unforced result"

    def test_a_real_lazy_in_the_result_is_materialised(
        self, mod, owns_rpc_model_method
    ):
        """End-to-end through the real ``_force_lazy_values``.

        What must hold is that the producer has ALREADY RUN by the time
        ``execute_cr`` returns — while the cursor is still open — not that the
        result stops being a ``lazy``.  ``lazy`` is a transparent proxy, so a
        forced one still satisfies ``isinstance(x, lazy)``; it just no longer
        needs the cursor to answer.  Counting producer calls is what actually
        distinguishes "forced here" from "forced later by the marshaller, after
        the cursor closed", which is the bug.
        """
        from odoo.tools import lazy

        produced = []

        def produce():
            produced.append(1)
            return 42

        cr = MagicMock()
        env = self._env(MagicMock())
        with (
            patch.object(mod.api, "Environment", return_value=env),
            patch.object(mod, "retrying", return_value={"total": lazy(produce)}),
        ):
            out = mod.execute_cr(cr, 7, "res.partner", "read", [[1]], {})
            assert produced == [1], (
                "the lazy was still unevaluated when execute_cr returned; it "
                "would materialise against a closed cursor"
            )
        assert out == {"total": 42}

    def test_unknown_model_raises_user_error(self, mod, owns_rpc_model_method):
        """``env.get`` returning ``None`` is "no such model"; it must not fall
        through to ``retrying`` with ``None`` as the recordset."""
        from odoo.exceptions import UserError

        cr = MagicMock()
        env = self._env(None)
        with (
            patch.object(mod.api, "Environment", return_value=env),
            patch.object(mod, "retrying") as retry,
        ):
            with pytest.raises(UserError, match="doesn't exist"):
                mod.execute_cr(cr, 7, "no.such.model", "read", [[1]], {})
        retry.assert_not_called()

    def test_the_call_is_routed_through_retrying(self, mod, owns_rpc_model_method):
        """``call_kw`` must not be invoked directly — the serialization-retry
        loop is the whole reason this indirection exists."""
        _result, _cr, env, retry = self._run(mod)
        retry.assert_called_once()
        thunk, passed_env = retry.call_args.args
        assert passed_env is env
        assert thunk.func is mod.call_kw
        assert thunk.args[1:] == ("read", [[1]], {})

    def test_thread_is_labelled_with_model_and_method(self, mod, owns_rpc_model_method):
        """The label the request log and ``rpc_model_method`` fragment read."""
        self._run(mod)
        assert threading.current_thread().rpc_model_method == "res.partner.read"

    def test_environment_is_built_under_the_caller_uid(
        self, mod, owns_rpc_model_method
    ):
        cr = MagicMock()
        env = self._env(MagicMock())
        with (
            patch.object(mod.api, "Environment", return_value=env) as environment,
            patch.object(mod, "retrying", return_value="ok"),
        ):
            mod.execute_cr(cr, 7, "res.partner", "read", [[1]], {})
        environment.assert_called_once_with(cr, 7, {})
        assert env.transaction.default_env is env


class TestCallKw:
    """``call_kw`` shapes the result (create -> id / ids, recordset -> ids) and
    rejects malformed argument lists.  These paths were previously untested
    because they were assumed to need a live Environment; they don't — the
    ORM method is supplied via ``get_public_method``, which we patch."""

    def _model(self):
        model = MagicMock()
        model._name = "res.partner"
        model.with_context.return_value = model
        return model

    def test_create_with_dict_vals_returns_scalar_id(self, mod):
        method = MagicMock(__name__="create", _api_model=True)
        method.return_value = MagicMock(id=42, ids=[42])
        with patch.object(mod, "get_public_method", return_value=method):
            out = mod.call_kw(self._model(), "create", [{"name": "x"}], {})
        assert out == 42

    def test_create_with_list_vals_returns_ids_list(self, mod):
        method = MagicMock(__name__="create", _api_model=True)
        method.return_value = MagicMock(id=1, ids=[1, 2])
        with patch.object(mod, "get_public_method", return_value=method):
            out = mod.call_kw(self._model(), "create", [[{"a": 1}, {"a": 2}]], {})
        assert out == [1, 2]

    def test_recordset_result_is_reduced_to_ids(self, mod):
        rs = MagicMock(spec=mod.BaseModel)
        rs.ids = [7, 8]
        method = MagicMock(__name__="search", _api_model=False, return_value=rs)
        with patch.object(mod, "get_public_method", return_value=method):
            out = mod.call_kw(self._model(), "search", [[1, 2]], {})
        assert out == [7, 8]

    def test_non_model_method_without_ids_raises_accesserror(self, mod):
        from odoo.exceptions import AccessError

        method = MagicMock(__name__="write")
        del method._api_model
        model = MagicMock()
        model._name = "res.partner"
        with patch.object(mod, "get_public_method", return_value=method):
            with pytest.raises(AccessError):
                mod.call_kw(model, "write", [], {})

    def test_ids_are_split_off_and_the_rest_stay_positional(self, mod):
        """``ids, args = args[0], args[1:]`` — the FIRST param is the id list and
        everything after it is forwarded verbatim.

        Found by mutation: ``args[2:]`` — which silently drops the first real
        argument of every non-``@api.model`` RPC call, e.g. the vals dict of a
        ``write`` — left the suite green.  The existing tests all pass a single
        param, where ``[1:]`` and ``[2:]`` are both empty.
        """
        method = MagicMock(__name__="write", return_value=True)
        del method._api_model
        model = self._model()
        with patch.object(mod, "get_public_method", return_value=method):
            mod.call_kw(model, "write", [[7, 8], {"name": "x"}, "extra"], {})
        model.browse.assert_called_once_with([7, 8])
        recs = model.browse.return_value.with_context.return_value
        method.assert_called_once_with(recs, {"name": "x"}, "extra")

    def test_the_caller_context_reaches_the_recordset(self, mod):
        """``kwargs.pop("context", None) or {}`` then ``with_context(...)``.

        Found by mutation: turning that ``or`` into ``and`` left the suite green
        — and it is not a cosmetic change.  With ``and``, a caller-supplied
        context evaluates to ``{}``, so every RPC call would silently lose its
        ``lang``, ``tz`` and ``allowed_company_ids``; and a call with no context
        passes ``None``, which is not a mapping.
        """
        method = MagicMock(__name__="read", return_value=[])
        del method._api_model
        model = self._model()
        ctx = {"lang": "es_MX", "tz": "America/Mexico_City"}
        with patch.object(mod, "get_public_method", return_value=method):
            mod.call_kw(model, "read", [[1]], {"context": ctx})
        model.browse.return_value.with_context.assert_called_once_with(ctx)

    def test_a_missing_context_becomes_an_empty_dict_not_none(self, mod):
        method = MagicMock(__name__="read", return_value=[])
        del method._api_model
        model = self._model()
        with patch.object(mod, "get_public_method", return_value=method):
            mod.call_kw(model, "read", [[1]], {})
        model.browse.return_value.with_context.assert_called_once_with({})

    def test_context_is_not_forwarded_as_a_keyword_argument(self, mod):
        """It is POPPED: an ORM method must not also receive ``context=`` in
        ``**kwargs``, which most signatures would reject outright."""
        method = MagicMock(__name__="read", return_value=[])
        del method._api_model
        model = self._model()
        with patch.object(mod, "get_public_method", return_value=method):
            mod.call_kw(model, "read", [[1]], {"context": {"lang": "en"}, "load": "_"})
        assert "context" not in method.call_args.kwargs
        assert method.call_args.kwargs == {"load": "_"}

    def test_create_without_vals_raises_accesserror_before_calling(self, mod):
        """The ``create`` arity guard must run BEFORE the ORM method.

        It used to sit beside the ``result.id``/``result.ids`` narrowing that
        needs ``args[0]`` — i.e. after the call — where it was dead code:
        ``create`` is ``@api.model``, so ``args`` reaches the ORM untouched and
        an argument-less RPC ``create`` raised ``TypeError: create() missing 1
        required positional argument: 'vals_list'`` (verified against a live
        registry) and never reached the guard.
        """
        from odoo.exceptions import AccessError

        method = MagicMock(__name__="create", _api_model=True)
        with patch.object(mod, "get_public_method", return_value=method):
            with pytest.raises(AccessError, match="requires a vals dict"):
                mod.call_kw(self._model(), "create", [], {})
        method.assert_not_called()


class TestDispatchValidation:
    """``dispatch`` validates the RPC envelope *before* touching the registry,
    so these hardening branches are reachable without a database:
    unknown verb -> AttributeError, too-few params -> TypeError, and the
    ``int(True) == 1`` admin-binding guard -> TypeError on a bool uid."""

    def test_unknown_verb_raises_attributeerror(self, mod):
        with pytest.raises(AttributeError):
            mod.dispatch("not_a_verb", ["db", 1, "pw", "res.partner", "read"])

    def test_too_few_params_raises_typeerror(self, mod):
        with pytest.raises(TypeError):
            mod.dispatch("execute", ["db", 1, "pw"])

    def test_unexposed_database_refused_before_registry(self, mod):
        """``execute_kw`` takes ``db`` off the wire and verifies credentials
        INSIDE the registry's cursor — so without an exposure gate an
        unauthenticated caller can make the server build a registry and a pool
        for any reachable database just by naming it.

        ``AccessDenied`` (not a distinct error class) so an unexposed name is
        indistinguishable from a wrong credential.
        """
        from odoo.exceptions import AccessDenied
        from odoo.tools import config

        def _must_not_run(*a, **kw):
            raise AssertionError("Registry must not be built for an unexposed db")

        with (
            config.patch(db_name=["served_db"]),
            patch.object(mod, "Registry", side_effect=_must_not_run),
        ):
            with pytest.raises(AccessDenied):
                mod.dispatch(
                    "execute", ["other_db", 1, "pw", "res.partner", "read", [1]]
                )

    @pytest.mark.parametrize("db", ["postgres", "template1"])
    def test_system_database_refused_before_registry(self, mod, db):
        """Never servable, and ``Registry.new`` objects with a ``ValueError``
        the RPC layer would surface as a 500 rather than AccessDenied."""
        from odoo.exceptions import AccessDenied

        def _must_not_run(*a, **kw):
            raise AssertionError("Registry must not be built for a system db")

        with patch.object(mod, "Registry", side_effect=_must_not_run):
            with pytest.raises(AccessDenied):
                mod.dispatch("execute", [db, 1, "pw", "res.partner", "read", [1]])

    def test_exposed_database_still_reaches_the_registry(self, mod):
        """The gate must not break the normal path: with ``--database`` unset
        (no declared allowlist) every ordinary name still goes through, and
        with it set the listed name does too."""
        from odoo.tools import config

        for options in ({"db_name": []}, {"db_name": ["served_db"]}):
            with (
                config.patch(**options),
                patch.object(mod, "Registry", side_effect=RuntimeError("reached")),
            ):
                with pytest.raises(RuntimeError, match="reached"):
                    mod.dispatch(
                        "execute", ["served_db", 1, "pw", "res.partner", "read", [1]]
                    )

    def test_absent_database_answers_access_denied(self, mod):
        """ "Database does not exist" must be indistinguishable from bad creds.

        ``/xmlrpc/2/object`` is ``auth="none"`` and the credential check runs
        INSIDE the registry's cursor, so an absent database answered with a
        distinct error class while an existing one answered ``AccessDenied`` —
        the same per-name existence oracle ``common.exp_authenticate`` closes.
        Closing it only there would have left this verb as the way around it.
        """
        from odoo.exceptions import AccessDenied

        with patch.object(
            mod,
            "Registry",
            side_effect=psycopg.errors.InvalidCatalogName('database "x" ...'),
        ):
            with pytest.raises(AccessDenied):
                mod.dispatch(
                    "execute", ["gone_db", 1, "pw", "res.partner", "read", [1]]
                )

    @pytest.mark.parametrize(
        ("exc_factory", "match"),
        [
            (lambda: psycopg.OperationalError("PG is down"), "PG is down"),
            (
                lambda: __import__("odoo.db", fromlist=["PoolError"]).PoolError(
                    "saturated"
                ),
                "saturated",
            ),
        ],
    )
    def test_real_outages_are_not_masked_as_access_denied(
        self, mod, exc_factory, match
    ):
        """ONLY the "does not exist" class collapses.

        A downed PG or a saturated pool says something true about an EXISTING
        database that an operator needs to see, and neither is an existence
        signal — masking them as ``AccessDenied`` would turn every outage into a
        phantom credentials problem.
        """
        with patch.object(mod, "Registry", side_effect=exc_factory()):
            with pytest.raises(Exception, match=match) as excinfo:
                mod.dispatch("execute", ["a_db", 1, "pw", "res.partner", "read", [1]])
        from odoo.exceptions import AccessDenied

        assert not isinstance(excinfo.value, AccessDenied)

    def test_bool_uid_rejected_before_registry(self, mod):
        with pytest.raises(TypeError):
            mod.dispatch("execute", ["db", True, "pw", "res.partner", "read", [1]])

    def test_float_uid_rejected_before_registry(self, mod):
        with pytest.raises(TypeError):
            mod.dispatch("execute", ["db", 1.9, "pw", "res.partner", "read", [1]])

    def test_empty_password_raises_accessdenied(self, mod):
        from odoo.exceptions import AccessDenied

        with pytest.raises(AccessDenied):
            mod.dispatch("execute", ["db", 1, "", "res.partner", "read", [1]])

    def test_exactly_five_params_is_enough_for_execute(self, mod):
        """The arity guard is ``len(params) < 5``, so FIVE is the legal minimum.

        Found by mutation: both ``<= 5`` and ``< 6`` — each of which rejects a
        perfectly well-formed ``execute`` call carrying no method arguments
        (``res.users.context_get`` is exactly this shape) — left the whole suite
        green.  The only arity test passed three params, so it could not see
        either side of the boundary.

        Driven to the point where the guard is behind us: a passing call reaches
        ``Registry``, which we make raise a sentinel.
        """
        with patch.object(mod, "Registry", side_effect=RuntimeError("past the guard")):
            with pytest.raises(RuntimeError, match="past the guard"):
                mod.dispatch("execute", ["db", 1, "pw", "res.partner", "read"])

    def test_four_params_is_still_too_few(self, mod):
        with pytest.raises(TypeError, match="at least 5"):
            mod.dispatch("execute", ["db", 1, "pw", "res.partner"])


class TestDispatchExecuteVersusExecuteKw:
    """``execute`` and ``execute_kw`` differ only in how the trailing params are
    shaped: ``execute`` passes them straight through with NO keyword arguments,
    ``execute_kw`` unpacks ``(args, kw)``.

    Nothing exercised that branch.  Every existing ``dispatch`` test stops at a
    validation guard or at ``Registry``, so the whole body after it was
    unreachable in tests: confirmed by mutation, inverting
    ``if dispatch_method == "execute"`` left the suite green — which means an
    ``execute`` call could have started being shaped like an ``execute_kw`` one
    (``args, kw = args`` on a 2-element arg list, silently swallowing the second
    argument as kwargs) with nothing to say so.
    """

    @staticmethod
    def _driven(mod, verb, params):
        """Run ``dispatch`` far enough to capture what ``execute_cr`` receives."""
        seen = {}

        def fake_execute_cr(cr, uid, model, method, args, kw):
            seen.update(uid=uid, model=model, method=method, args=args, kw=kw)
            return "ok"

        registry = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        registry.check_signaling.return_value = registry
        registry.cursor.return_value = cursor

        with (
            patch.object(mod, "Registry", return_value=registry),
            patch.object(mod, "execute_cr", fake_execute_cr),
            patch("odoo.api.Environment"),
        ):
            result = mod.dispatch(verb, params)
        return result, seen

    def test_execute_passes_its_arguments_through_with_no_kwargs(self, mod):
        _result, seen = self._driven(
            mod, "execute", ["db", 1, "pw", "res.partner", "read", [7], ["name"]]
        )
        assert seen["args"] == [[7], ["name"]], (
            "execute must forward every trailing param as positional args"
        )
        assert seen["kw"] == {}, "execute takes no keyword arguments"

    def test_execute_kw_unpacks_args_and_kw(self, mod):
        _result, seen = self._driven(
            mod,
            "execute_kw",
            ["db", 1, "pw", "res.partner", "read", [7], {"context": {"lang": "en"}}],
        )
        assert seen["args"] == [7]
        assert seen["kw"] == {"context": {"lang": "en"}}

    def test_execute_kw_defaults_missing_kw_to_an_empty_dict(self, mod):
        _result, seen = self._driven(
            mod, "execute_kw", ["db", 1, "pw", "res.partner", "read", [7]]
        )
        assert seen["args"] == [7]
        assert seen["kw"] == {}

    def test_execute_kw_treats_an_explicit_none_kw_as_empty(self, mod):
        _result, seen = self._driven(
            mod, "execute_kw", ["db", 1, "pw", "res.partner", "read", [7], None]
        )
        assert seen["kw"] == {}

    def test_the_credentials_are_checked_before_the_call(self, mod):
        """``_check_uid_passwd`` runs inside the registry's cursor, before
        ``execute_cr`` — the only thing standing between an ``auth="none"``
        endpoint and the ORM."""
        from odoo.exceptions import AccessDenied

        registry = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        registry.check_signaling.return_value = registry
        registry.cursor.return_value = cursor

        users = MagicMock()
        users._check_uid_passwd.side_effect = AccessDenied
        env = MagicMock()
        env.__getitem__ = MagicMock(return_value=users)

        with (
            patch.object(mod, "Registry", return_value=registry),
            patch.object(mod, "execute_cr") as execute_cr,
            patch("odoo.api.Environment", return_value=env),
        ):
            with pytest.raises(AccessDenied):
                mod.dispatch("execute", ["db", 1, "bad", "res.partner", "read"])
        execute_cr.assert_not_called()


class TestDispatchArgShape:
    def test_execute_kw_bad_arg_shape_raises_typeerror(self, mod):
        with patch.object(mod, "Registry") as reg:
            reg.return_value.check_signaling.return_value = reg.return_value
            with pytest.raises(TypeError):
                mod.dispatch(
                    "execute_kw",
                    ["db", 1, "pw", "res.partner", "read", [1], {}, "extra"],
                )
