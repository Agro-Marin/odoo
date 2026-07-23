"""Pure-pytest tests for ``odoo.service.model``.

Covers the mockable, database-free portions of the service layer:
  - ``Params.__str__()``
  - ``get_public_method()`` — RPC access-control gate
  - ``_force_lazy_values()`` — recursive lazy-value forcing
  - ``retrying()`` — PostgreSQL serialization-retry loop

NOT covered here (require a live cursor / registry / ORM):
  - ``call_kw()`` / ``execute_cr()`` / ``dispatch()`` — need real Environment

Run with::

    python -m pytest tests/service/ -v
"""

import random
import time
from collections.abc import Callable
from contextlib import suppress
from unittest.mock import MagicMock, call, patch

import psycopg
import psycopg.errors
import pytest


# ---------------------------------------------------------------------------
# Module-scope import (heavy import chain — paid once per session)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mod():
    """Return ``odoo.service.model``, imported once per session."""
    import odoo.service.model as m  # noqa: PLC0415

    return m


@pytest.fixture(scope="module")
def tx():
    """Return ``odoo.service.transaction`` (home of ``retrying`` + its constants)."""
    import odoo.service.transaction as t  # noqa: PLC0415

    return t


# ---------------------------------------------------------------------------
# Helpers used across multiple test classes
# ---------------------------------------------------------------------------


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
        # psycopg stores the sqlstate on the class for PG_CONCURRENCY_EXCEPTIONS_TO_RETRY
        self.sqlstate = "23505"

    @property
    def diag(self):
        return self._diag_mock


@pytest.fixture()
def mock_env():
    """Minimal Environment stub for ``retrying()``."""
    e = MagicMock()
    e.cr._closed = False
    e.cr.closed = False
    e.cr.flush = MagicMock()
    e.cr.rollback = MagicMock()
    e.cr.commit = MagicMock()
    e.transaction.reset = MagicMock()
    e.registry.reset_changes = MagicMock()
    e.registry.signal_changes = MagicMock()
    e.registry.values.return_value = []
    # env._() translation helper — forward the template as-is for assertions
    e._.side_effect = lambda tmpl, *args: tmpl % args if args else tmpl
    return e


# ---------------------------------------------------------------------------
# TestGetPublicMethod
# ---------------------------------------------------------------------------


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


# Mark the api-private method
_FakeModel.api_private_method._api_private = True  # type: ignore[attr-defined]


class TestGetPublicMethod:
    """get_public_method() enforces RPC access control rules."""

    @pytest.fixture()
    def fake_model(self, mod):
        """Return a _FakeModel instance with BaseModel patched in the module."""
        instance = _FakeModel()
        with patch.object(mod, "BaseModel", _FakeBaseModel):
            yield instance

    def test_underscore_prefix_blocked(self, mod, fake_model) -> None:
        from odoo.exceptions import AccessError  # noqa: PLC0415

        with patch.object(mod, "BaseModel", _FakeBaseModel):
            with pytest.raises(AccessError):
                mod.get_public_method(fake_model, "_underscore")

    def test_unsafe_attribute_blocked(self, mod, fake_model) -> None:
        from odoo.exceptions import AccessError  # noqa: PLC0415

        # "__class__" is in _UNSAFE_ATTRIBUTES
        with patch.object(mod, "BaseModel", _FakeBaseModel):
            with pytest.raises(AccessError):
                mod.get_public_method(fake_model, "__class__")

    def test_api_private_blocked(self, mod, fake_model) -> None:
        from odoo.exceptions import AccessError  # noqa: PLC0415

        with patch.object(mod, "BaseModel", _FakeBaseModel):
            with pytest.raises(AccessError):
                mod.get_public_method(fake_model, "api_private_method")

    def test_non_callable_raises_attribute_error(self, mod, fake_model) -> None:
        with patch.object(mod, "BaseModel", _FakeBaseModel):
            with pytest.raises(AttributeError):
                mod.get_public_method(fake_model, "not_callable")

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
        from odoo.exceptions import AccessError  # noqa: PLC0415

        class Base(_FakeBaseModel):
            def deep_private(self) -> str:
                return "from base"

        Base.deep_private._api_private = True  # type: ignore[attr-defined]

        # Three levels of inheritance — method is only in Base.__dict__
        class Mid(Base):
            pass

        class Leaf(Mid):
            pass

        leaf_instance = Leaf()
        with patch.object(mod, "BaseModel", _FakeBaseModel):
            with pytest.raises(AccessError):
                mod.get_public_method(leaf_instance, "deep_private")


# ---------------------------------------------------------------------------
# TestForceLazyValues
# ---------------------------------------------------------------------------


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

    def test_lazy_as_dict_key_forced(self, mod) -> None:
        # Dict keys are traversed too — a lazy can legitimately be a key.
        lz, forced = _tracked_lazy()
        mod._force_lazy_values({lz: "value"})
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
        # ``dict_values`` is neither Sequence nor Set — exercises the generic
        # Iterable fallback that the previous design once mishandled.
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
        # One-shot iterators are materialized so the marshaller gets a real list.
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
        # A str is a Sequence; descending it would recurse char-by-char forever.
        assert mod._force_lazy_values(["abc"]) == ["abc"]

    def test_str_subclass_does_not_infinite_recurse(self, mod) -> None:
        class MyStr(str):
            __slots__ = ()

        # Exact-class fast path misses a str *subclass*; the isinstance(str)
        # guard after it must still stop the char-by-char recursion.
        mod._force_lazy_values({"k": MyStr("abcdef")})  # must not RecursionError

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
            OrderedSet([10, 20]),  # scalars only — nothing to force
            {"k": (s3, "txt", 99)},
        ]
        mod._force_lazy_values(result)
        assert sorted(seen) == [1, 2, 3]

    def test_scalar_heavy_collection_still_forces_lazy(self, mod) -> None:
        # The exact-scalar fast path skips the ABC walk for ints/floats/bools/
        # None/str/bytes; a lazy mixed in with those (and nested in a dict) must
        # still be forced.
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
        # Must not raise; the same object comes back for the marshaller to handle.
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
        # No exception; the marshaller decides what to do with it.
        mod._force_lazy_values(deep)


# ---------------------------------------------------------------------------
# TestRetrying
# ---------------------------------------------------------------------------


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

        with patch("odoo.http") as mock_http, \
             patch("odoo.service.transaction.time") as mock_time, \
             patch("odoo.service.transaction.random") as mock_random:
            mock_http.request = None
            mock_random.uniform.return_value = 0.0
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

        with patch("odoo.http") as mock_http, \
             patch("odoo.service.transaction.time") as mock_time, \
             patch("odoo.service.transaction.random") as mock_random:
            mock_http.request = None
            mock_random.uniform.return_value = 0.0
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

        with patch("odoo.http") as mock_http, \
             patch("odoo.service.transaction.time") as mock_time, \
             patch("odoo.service.transaction.random") as mock_random:
            mock_http.request = None
            mock_random.uniform.return_value = 0.0
            result = mod.retrying(func, mock_env)

        assert result == "ok"
        assert calls == 2

    def test_max_retries_exhausted_raises(self, mod, mock_env) -> None:
        """After MAX_TRIES_ON_CONCURRENCY_FAILURE, the last exception propagates."""
        exc = psycopg.errors.SerializationFailure()
        exc.sqlstate = "40001"

        def func():
            raise exc

        with patch("odoo.http") as mock_http, \
             patch("odoo.service.transaction.time"), \
             patch("odoo.service.transaction.random") as mock_random:
            mock_http.request = None
            mock_random.uniform.return_value = 0.0
            with pytest.raises(psycopg.errors.SerializationFailure):
                mod.retrying(func, mock_env)

    def test_sleep_called_between_retries_not_on_last(self, mod, tx, mock_env) -> None:
        """time.sleep is called N-1 times for N attempts (no sleep after last failure)."""
        exc = psycopg.errors.SerializationFailure()
        exc.sqlstate = "40001"
        max_tries = tx.MAX_TRIES_ON_CONCURRENCY_FAILURE

        def func():
            raise exc

        with patch("odoo.http") as mock_http, \
             patch("odoo.service.transaction.time") as mock_time, \
             patch("odoo.service.transaction.random") as mock_random:
            mock_http.request = None
            mock_random.uniform.return_value = 0.0
            with suppress(psycopg.errors.SerializationFailure):
                mod.retrying(func, mock_env)

        assert mock_time.sleep.call_count == max_tries - 1

    def test_integrity_error_converted_to_validation_error(self, mod, mock_env) -> None:
        """IntegrityError → ValidationError with the model's sql_error_to_message."""
        from odoo.exceptions import ValidationError  # noqa: PLC0415

        exc = _FakeIntegrityError(table_name="some_table")

        # Provide a model that matches the table name
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
            with pytest.raises(ValidationError, match="The operation cannot be completed"):
                mod.retrying(func, mock_env)

    def test_integrity_error_with_closed_connection_reraises(self, mod, mock_env) -> None:
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
        "wrapper_closed,conn_dead",
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
        # The cursor.closed property is `_closed or bool(_cnx.closed)`.  Reproduce
        # both inputs so the parametrized cases cover the full truth table.
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

        with patch("odoo.http") as mock_http, \
             patch("odoo.service.transaction.time"), \
             patch("odoo.service.transaction.random") as mock_random:
            mock_http.request = None
            mock_random.uniform.return_value = 0.0
            result = mod.retrying(func, mock_env)

        assert result == "ok"

    def test_outer_except_resets_registry_on_non_retryable_error(self, mod, mock_env) -> None:
        """On a non-retryable exception, outer except runs transaction.reset and registry.reset_changes."""
        exc = ValueError("boom")

        def func():
            raise exc

        with pytest.raises(ValueError, match="boom"):
            mod.retrying(func, mock_env)

        mock_env.transaction.reset.assert_called()
        mock_env.registry.reset_changes.assert_called()

    def test_outer_except_skips_reset_when_connection_closed(self, mod, mock_env) -> None:
        """When connection is dead, outer except skips transaction.reset."""
        mock_env.cr.closed = True
        exc = ValueError("boom")

        def func():
            raise exc

        with pytest.raises(ValueError, match="boom"):
            mod.retrying(func, mock_env)

        mock_env.transaction.reset.assert_not_called()
        mock_env.registry.reset_changes.assert_not_called()

    def test_request_session_refreshed_and_files_rewound_on_retry(self, mod, mock_env) -> None:
        """On a concurrency error with an active HTTP request, the session is refreshed
        and seekable uploaded files are rewound so the retry reads them from the start."""
        exc = psycopg.errors.SerializationFailure()
        exc.sqlstate = "40001"
        new_session = MagicMock()
        mock_file = MagicMock()
        mock_file.seekable.return_value = True

        mock_request = MagicMock()
        mock_request._get_session_and_dbname.return_value = (new_session, "testdb")
        mock_request.httprequest.files.items.return_value = [("photo", mock_file)]

        calls = 0

        def func():
            nonlocal calls
            calls += 1
            if calls < 2:
                raise exc
            return "ok"

        with patch("odoo.http") as mock_http, \
             patch("odoo.service.transaction.time"), \
             patch("odoo.service.transaction.random") as mock_random:
            mock_http.request = mock_request
            mock_random.uniform.return_value = 0.0
            result = mod.retrying(func, mock_env)

        assert result == "ok"
        assert mock_request.session is new_session
        mock_file.seek.assert_called_once_with(0)

    def test_non_seekable_file_raises_runtime_error_on_retry(self, mod, mock_env) -> None:
        """If an uploaded file cannot be seeked, retrying must raise RuntimeError
        rather than silently replaying a partially-consumed stream."""
        exc = psycopg.errors.SerializationFailure()
        exc.sqlstate = "40001"
        mock_file = MagicMock()
        mock_file.seekable.return_value = False

        mock_request = MagicMock()
        mock_request._get_session_and_dbname.return_value = (MagicMock(), "testdb")
        mock_request.httprequest.files.items.return_value = [("upload", mock_file)]

        def func():
            raise exc

        with patch("odoo.http") as mock_http, \
             patch("odoo.service.transaction.time"), \
             patch("odoo.service.transaction.random") as mock_random:
            mock_http.request = mock_request
            mock_random.uniform.return_value = 0.0
            with pytest.raises(RuntimeError, match="Cannot retry request on input file 'upload'"):
                mod.retrying(func, mock_env)

    # -- commit-time failures: the final commit() runs in its own guarded
    # block, so a failure there (deferred constraint, post-commit hook) is
    # NOT retried but DOES get the same cleanup/translation as an in-loop one.

    def test_commit_time_failure_runs_cleanup_without_retry(self, mod, mock_env) -> None:
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

        assert calls == 1  # commit-time failure was NOT retried
        mock_env.transaction.reset.assert_called()  # cleanup ran
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
            with pytest.raises(ValidationError, match="The operation cannot be completed"):
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
            with pytest.raises(_FakeIntegrityError):  # raw, not ValidationError
                mod.retrying(lambda: "ok", mock_env)


# ---------------------------------------------------------------------------
# TestRetryVocabularyMatchesPostgres — the retry SQLSTATE / exception lists
# must describe the SAME real PG errors (mock-reality bridge)
# ---------------------------------------------------------------------------


class TestRetryVocabularyMatchesPostgres:
    """The retry SQLSTATE set and exception-class tuple must stay in sync with
    each other AND with psycopg's own SQLSTATE→class mapping.

    ``retrying()`` recognises a retryable failure via
    ``isinstance(exc, PG_CONCURRENCY_EXCEPTIONS_TO_RETRY)`` and then logs it with
    ``errors.lookup(exc.sqlstate).__name__``.  If the two lists drift — or drift
    from psycopg — a real serialization failure would either silently not retry
    or crash the logging path.  The rest of ``TestRetrying`` uses hand-built mock
    exceptions; these tests pin the vocabulary to psycopg's real mapping so a
    genuine cluster error (verified live: 40001/40P01/55P03) is always handled,
    without needing a database.
    """

    def test_every_retry_sqlstate_maps_to_an_exception_in_the_tuple(self, tx) -> None:
        for sqlstate in tx.PG_CONCURRENCY_ERRORS_TO_RETRY:
            cls = psycopg.errors.lookup(sqlstate)
            assert issubclass(cls, tx.PG_CONCURRENCY_EXCEPTIONS_TO_RETRY), (
                f"sqlstate {sqlstate!r} maps to {cls.__name__}, which is absent "
                f"from PG_CONCURRENCY_EXCEPTIONS_TO_RETRY — retrying() would not "
                f"retry a real error carrying this sqlstate"
            )

    def test_canonical_concurrency_errors_are_recognised(self, tx) -> None:
        """The three errors a real cluster raises under contention must each be
        an instance of the retry tuple and carry a retryable sqlstate."""
        for name, sqlstate in [
            ("SerializationFailure", "40001"),
            ("DeadlockDetected", "40P01"),
            ("LockNotAvailable", "55P03"),
        ]:
            cls = getattr(psycopg.errors, name)
            assert issubclass(cls, tx.PG_CONCURRENCY_EXCEPTIONS_TO_RETRY), name
            assert sqlstate in tx.PG_CONCURRENCY_ERRORS_TO_RETRY, name


# ---------------------------------------------------------------------------
# TestRetryingRequestSideEffects — session refresh vs upload rewind ordering
# ---------------------------------------------------------------------------


class TestRetryingRequestSideEffects:
    """``retrying()`` with an in-flight HTTP request: the session re-fetch runs
    on EVERY failure path (transaction-coupled session mutations must not
    outlive the rollback), but the upload rewind runs ONLY when a retry is
    certain — on the raise paths it would be wasted work, and a non-seekable
    upload would raise RuntimeError and mask the real error."""

    @staticmethod
    def _request():
        request = MagicMock()
        request._get_session_and_dbname.return_value = ("fresh-session", "db")
        return request

    def test_retry_refreshes_session_and_rewinds_files(self, mod, mock_env) -> None:
        exc = psycopg.errors.SerializationFailure()
        exc.sqlstate = "40001"
        calls = 0

        def func():
            nonlocal calls
            calls += 1
            if calls < 2:
                raise exc
            return "ok"

        request = self._request()
        with patch("odoo.http") as mock_http, \
             patch("odoo.http.helpers.rewind_uploaded_files") as mock_rewind, \
             patch("odoo.service.transaction.time"), \
             patch("odoo.service.transaction.random") as mock_random:
            mock_http.request = request
            mock_random.uniform.return_value = 0.0
            assert mod.retrying(func, mock_env) == "ok"

        assert request.session == "fresh-session"
        mock_rewind.assert_called_once_with(request.httprequest, cause=exc)

    def test_integrity_error_refreshes_session_but_skips_rewind(
        self, mod, mock_env
    ) -> None:
        """A non-seekable upload used to turn the friendly ValidationError into
        an opaque RuntimeError; the rewind must not run on this path at all."""
        from odoo.exceptions import ValidationError  # noqa: PLC0415

        exc = _FakeIntegrityError(table_name="some_table")
        matching_model = MagicMock()
        matching_model._name = "some.model"
        matching_model._table = "some_table"
        matching_model._sql_error_to_message.return_value = "Unique constraint"
        mock_env.registry.values.return_value = [matching_model]
        mock_env.__getitem__ = MagicMock(return_value=matching_model)

        def func():
            raise exc

        request = self._request()
        with patch("odoo.http") as mock_http, \
             patch("odoo.http.helpers.rewind_uploaded_files") as mock_rewind:
            mock_http.request = request
            with pytest.raises(ValidationError):
                mod.retrying(func, mock_env)

        request._get_session_and_dbname.assert_called()
        mock_rewind.assert_not_called()

    def test_non_retryable_operational_error_skips_rewind(
        self, mod, mock_env
    ) -> None:
        exc = psycopg.OperationalError("connection reset")
        exc.sqlstate = None

        def func():
            raise exc

        request = self._request()
        with patch("odoo.http") as mock_http, \
             patch("odoo.http.helpers.rewind_uploaded_files") as mock_rewind:
            mock_http.request = request
            with pytest.raises(psycopg.OperationalError):
                mod.retrying(func, mock_env)

        request._get_session_and_dbname.assert_called()
        mock_rewind.assert_not_called()

    def test_retries_exhausted_skips_final_rewind(self, mod, mock_env, tx) -> None:
        """The rewind pairs with a replay: after the LAST failure there is no
        replay, so N attempts rewind N-1 times."""
        exc = psycopg.errors.SerializationFailure()
        exc.sqlstate = "40001"

        def func():
            raise exc

        request = self._request()
        with patch("odoo.http") as mock_http, \
             patch("odoo.http.helpers.rewind_uploaded_files") as mock_rewind, \
             patch("odoo.service.transaction.time"), \
             patch("odoo.service.transaction.random") as mock_random:
            mock_http.request = request
            mock_random.uniform.return_value = 0.0
            with pytest.raises(psycopg.errors.SerializationFailure):
                mod.retrying(func, mock_env)

        assert mock_rewind.call_count == tx.MAX_TRIES_ON_CONCURRENCY_FAILURE - 1


# ---------------------------------------------------------------------------
# TestCallKw — result shaping + access-control, no live DB
# ---------------------------------------------------------------------------


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
        # A non-create method returning a BaseModel must be marshalled to .ids.
        rs = MagicMock(spec=mod.BaseModel)
        rs.ids = [7, 8]
        method = MagicMock(__name__="search", _api_model=False, return_value=rs)
        with patch.object(mod, "get_public_method", return_value=method):
            out = mod.call_kw(self._model(), "search", [[1, 2]], {})
        assert out == [7, 8]

    def test_non_model_method_without_ids_raises_accesserror(self, mod):
        from odoo.exceptions import AccessError  # noqa: PLC0415

        method = MagicMock(__name__="write")
        del method._api_model  # getattr(..., "_api_model", False) -> False
        model = MagicMock()
        model._name = "res.partner"
        with patch.object(mod, "get_public_method", return_value=method):
            with pytest.raises(AccessError):
                mod.call_kw(model, "write", [], {})  # no ids in args


# ---------------------------------------------------------------------------
# TestDispatchValidation — the object-service RPC gateway, no live DB
# ---------------------------------------------------------------------------


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
            mod.dispatch("execute", ["db", 1, "pw"])  # < 5 positional args

    def test_bool_uid_rejected_before_registry(self, mod):
        # int(True) == 1 would silently bind uid to admin; reject it with a
        # typed error. This fires before Registry(db), so no DB is needed.
        with pytest.raises(TypeError):
            mod.dispatch(
                "execute", ["db", True, "pw", "res.partner", "read", [1]]
            )

    def test_float_uid_rejected_before_registry(self, mod):
        # int(1.9) == 1 would silently truncate a float uid to admin; require an
        # exact int, like the bool guard above.  Fires before Registry(db).
        with pytest.raises(TypeError):
            mod.dispatch(
                "execute", ["db", 1.9, "pw", "res.partner", "read", [1]]
            )

    def test_empty_password_raises_accessdenied(self, mod):
        from odoo.exceptions import AccessDenied  # noqa: PLC0415

        with pytest.raises(AccessDenied):
            mod.dispatch(
                "execute", ["db", 1, "", "res.partner", "read", [1]]
            )

    def test_execute_kw_bad_arg_shape_raises_typeerror(self, mod):
        # execute_kw accepts (args, [kw]); 3 trailing positionals is malformed.
        # Patch Registry so we exercise the arg-shape guard, not DB access.
        with patch.object(mod, "Registry") as reg:
            reg.return_value.check_signaling.return_value = reg.return_value
            with pytest.raises(TypeError):
                mod.dispatch(
                    "execute_kw",
                    ["db", 1, "pw", "res.partner", "read", [1], {}, "extra"],
                )
