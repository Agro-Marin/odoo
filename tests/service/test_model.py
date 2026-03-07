"""Pure-pytest tests for ``odoo.service.model``.

Covers the mockable, database-free portions of the service layer:
  - ``Params.__str__()``
  - ``get_public_method()`` — RPC access-control gate
  - ``_traverse_containers()`` — recursive lazy-value harvester
  - ``retrying()`` — PostgreSQL serialization-retry loop

NOT covered here (require a live cursor / registry / ORM):
  - ``call_kw()`` / ``execute_cr()`` / ``dispatch()`` — need real Environment

Run with::

    python -m pytest core/tests/service/ -v
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
# TestTraverseContainers
# ---------------------------------------------------------------------------


class _Marker:
    """Sentinel type for traverse tests."""


class TestTraverseContainers:
    """_traverse_containers() yields matching atoms, traverses standard containers."""

    def test_atom_match_yielded(self, mod) -> None:
        m = _Marker()
        assert list(mod._traverse_containers(m, _Marker)) == [m]

    def test_str_stops_traversal(self, mod) -> None:
        # str is a Sequence but must not be descended into
        assert list(mod._traverse_containers("hello", str)) == ["hello"]

    def test_bytes_stops_traversal(self, mod) -> None:
        assert list(mod._traverse_containers(b"data", bytes)) == [b"data"]

    def test_non_matching_atom_skipped(self, mod) -> None:
        assert list(mod._traverse_containers(42, _Marker)) == []

    def test_list_traversed(self, mod) -> None:
        m1, m2 = _Marker(), _Marker()
        result = list(mod._traverse_containers([m1, "skip", m2], _Marker))
        assert result == [m1, m2]

    def test_nested_list(self, mod) -> None:
        m = _Marker()
        result = list(mod._traverse_containers([[m]], _Marker))
        assert result == [m]

    def test_mapping_values_traversed(self, mod) -> None:
        m = _Marker()
        result = list(mod._traverse_containers({"key": m}, _Marker))
        assert result == [m]

    def test_mapping_keys_traversed(self, mod) -> None:
        """Dict keys are also traversed — important for lazy values in keys."""
        m = _Marker()
        result = list(mod._traverse_containers({m: "value"}, _Marker))
        assert result == [m]

    def test_str_in_sequence_not_descended(self, mod) -> None:
        # "abc" treated as atom, not recursed into as Sequence[str]
        assert list(mod._traverse_containers(["abc"], str)) == ["abc"]


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
        """When cr._closed is True after func(), skip flush; when cr.closed, skip commit."""
        mock_env.cr._closed = True
        mock_env.cr.closed = True

        result = mod.retrying(lambda: "done", mock_env)

        assert result == "done"
        mock_env.cr.flush.assert_not_called()
        mock_env.cr.commit.assert_not_called()

    def test_plain_operational_error_not_retried(self, mod, mock_env) -> None:
        """A bare OperationalError (not a concurrency subtype) re-raises immediately."""
        exc = psycopg.OperationalError("connection reset")
        calls = 0

        def func():
            nonlocal calls
            calls += 1
            raise exc

        with patch("odoo.service.model.http") as mock_http:
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

        with patch("odoo.service.model.http") as mock_http, \
             patch("odoo.service.model.time") as mock_time, \
             patch("odoo.service.model.random") as mock_random:
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

        with patch("odoo.service.model.http") as mock_http, \
             patch("odoo.service.model.time") as mock_time, \
             patch("odoo.service.model.random") as mock_random:
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

        with patch("odoo.service.model.http") as mock_http, \
             patch("odoo.service.model.time") as mock_time, \
             patch("odoo.service.model.random") as mock_random:
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

        with patch("odoo.service.model.http") as mock_http, \
             patch("odoo.service.model.time"), \
             patch("odoo.service.model.random") as mock_random:
            mock_http.request = None
            mock_random.uniform.return_value = 0.0
            with pytest.raises(psycopg.errors.SerializationFailure):
                mod.retrying(func, mock_env)

    def test_sleep_called_between_retries_not_on_last(self, mod, mock_env) -> None:
        """time.sleep is called N-1 times for N attempts (no sleep after last failure)."""
        exc = psycopg.errors.SerializationFailure()
        exc.sqlstate = "40001"
        max_tries = mod.MAX_TRIES_ON_CONCURRENCY_FAILURE

        def func():
            raise exc

        with patch("odoo.service.model.http") as mock_http, \
             patch("odoo.service.model.time") as mock_time, \
             patch("odoo.service.model.random") as mock_random:
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

        with patch("odoo.service.model.http") as mock_http:
            mock_http.request = None
            with pytest.raises(ValidationError, match="The operation cannot be completed"):
                mod.retrying(func, mock_env)

    def test_integrity_error_with_closed_connection_reraises(self, mod, mock_env) -> None:
        """IntegrityError + closed connection re-raises without ValidationError conversion."""
        exc = _FakeIntegrityError()
        # cr._closed=False so rollback path runs; cr.closed=True so IntegrityError path re-raises
        mock_env.cr._closed = False
        mock_env.cr.closed = True

        def func():
            raise exc

        with patch("odoo.service.model.http") as mock_http:
            mock_http.request = None
            with pytest.raises(_FakeIntegrityError):
                mod.retrying(func, mock_env)

    def test_closed_cursor_in_inner_except_reraises_immediately(self, mod, mock_env) -> None:
        """If cr._closed when catching concurrency error, re-raise without retry."""
        mock_env.cr._closed = True
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

        with patch("odoo.service.model.http") as mock_http, \
             patch("odoo.service.model.time"), \
             patch("odoo.service.model.random") as mock_random:
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

        with patch("odoo.service.model.http") as mock_http, \
             patch("odoo.service.model.time"), \
             patch("odoo.service.model.random") as mock_random:
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

        with patch("odoo.service.model.http") as mock_http, \
             patch("odoo.service.model.time"), \
             patch("odoo.service.model.random") as mock_random:
            mock_http.request = mock_request
            mock_random.uniform.return_value = 0.0
            with pytest.raises(RuntimeError, match="Cannot retry request on input file 'upload'"):
                mod.retrying(func, mock_env)
