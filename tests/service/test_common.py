"""Pure-pytest tests for ``odoo.service.common``.

Covers the RPC dispatch allowlist — specifically, the regression that
replaced ``globals()`` reflection with an explicit ``_DISPATCH`` dict.

Run with::

    python -m pytest tests/service/test_common.py -v
"""

from unittest.mock import patch

import pytest


@pytest.fixture(scope="module")
def common_mod():
    """Import ``odoo.service.common`` once per session."""
    import odoo.service.common as mod  # noqa: PLC0415

    return mod


# ---------------------------------------------------------------------------
# dispatch() allowlist
# ---------------------------------------------------------------------------


class TestDispatchAllowlist:
    """``dispatch()`` must only expose methods present in ``_DISPATCH``.

    Regression: the prior implementation used ``globals()`` reflection —
    ANY module-level function prefixed ``exp_`` was reachable by an
    unauthenticated XML-RPC caller. The explicit allowlist prevents a
    future debug helper or operator tool from becoming a public endpoint.
    """

    def test_allowlist_contains_expected_public_methods(self, common_mod):
        """The three documented RPC methods must be reachable."""
        assert set(common_mod._DISPATCH) == {"login", "authenticate", "version"}

    def test_unknown_method_raises(self, common_mod):
        """A method not in the allowlist must raise, not silently call nothing."""
        with pytest.raises(AttributeError, match="Method not found"):
            common_mod.dispatch("not_a_real_method", [])

    def test_accidental_exp_helper_is_not_reachable(self, common_mod):
        """Adding a module-level ``exp_*`` function does NOT expose it.

        Simulates a future maintainer writing a debug helper they forgot
        was prefixed ``exp_``. Under the old globals()-based dispatch,
        this would be callable unauthenticated; under the allowlist, it is not.
        """

        def exp_accidental_debug_helper():
            return "this should never be reachable via RPC"

        # Inject the helper at module level just as a real contributor would
        with patch.object(common_mod, "exp_accidental_debug_helper", exp_accidental_debug_helper, create=True):
            # Must NOT be exposed by dispatch
            with pytest.raises(AttributeError, match="Method not found"):
                common_mod.dispatch("accidental_debug_helper", [])

    def test_version_dispatch_matches_direct_call(self, common_mod):
        """Documented methods must behave identically via dispatch and directly."""
        direct = common_mod.exp_version()
        via_dispatch = common_mod.dispatch("version", [])
        assert direct == via_dispatch

    def test_allowlist_values_are_callable(self, common_mod):
        """Each allowlist value must be a real callable, not a typo."""
        for name, handler in common_mod._DISPATCH.items():
            assert callable(handler), f"{name!r} maps to non-callable {handler!r}"

    def test_login_is_a_thin_wrapper_over_authenticate(self, common_mod):
        """``exp_login(db, user, pw)`` must delegate to ``exp_authenticate(..., None)``."""
        with patch.object(common_mod, "exp_authenticate", return_value=42) as mock:
            result = common_mod.exp_login("mydb", "alice", "pw")
        mock.assert_called_once_with("mydb", "alice", "pw", None)
        assert result == 42


# ---------------------------------------------------------------------------
# exp_authenticate — connection-failure exceptions must NOT escape
# ---------------------------------------------------------------------------


class TestExpAuthenticateExceptionAbsorption:
    """``exp_authenticate`` collapses every connection-level failure into ``False``.

    Regression: the prior catch was ``except psycopg.OperationalError, LookupError:``.
    Today's connection layer wraps every ``getconn`` failure (missing DB, dead PG,
    bad credentials, semaphore saturation) in ``odoo.db.PoolError`` — which is not
    a subclass of either caught exception.  An attacker could distinguish a
    missing database (``False``) from an existing-but-overloaded one (``PoolError``
    propagated to the RPC layer), defeating the database-enumeration mitigation
    documented in the function's own docstring.

    LookupError was also dropped from the catch — it never matched the real-world
    failure modes (``Registry.__new__`` swallows the only KeyError it can raise),
    and catching it silently swallowed any unrelated ``KeyError`` programming
    error.
    """

    def test_pool_error_returns_false_not_raise(self, common_mod):
        """PoolError from the DB layer must collapse to ``False`` like AccessDenied."""
        from odoo.db import PoolError  # noqa: PLC0415

        with patch.object(
            common_mod, "Registry", side_effect=PoolError("pool exhausted")
        ):
            assert common_mod.exp_authenticate("any_db", "u", "p", None) is False

    def test_psycopg_operational_error_still_returns_false(self, common_mod):
        """Regression-check the surviving catch: bypass paths that don't go
        through the pool (direct ``psycopg.connect`` from migration scripts)
        still raise ``OperationalError`` and must still collapse to ``False``."""
        import psycopg  # noqa: PLC0415

        with patch.object(
            common_mod, "Registry", side_effect=psycopg.OperationalError("PG down")
        ):
            assert common_mod.exp_authenticate("any_db", "u", "p", None) is False

    def test_unrelated_keyerror_propagates(self, common_mod):
        """Programming errors must NOT be silently swallowed.

        The prior ``LookupError`` catch incidentally caught ``KeyError`` (a
        ``LookupError`` subclass) raised by application bugs inside Registry
        construction.  Removing ``LookupError`` from the catch ensures those
        bugs surface in logs and tracebacks.
        """
        with patch.object(
            common_mod, "Registry", side_effect=KeyError("missing module")
        ):
            with pytest.raises(KeyError, match="missing module"):
                common_mod.exp_authenticate("any_db", "u", "p", None)

    def test_runtime_error_still_propagates(self, common_mod):
        """An unrelated RuntimeError still surfaces — only connection failures
        are collapsed to ``False``."""
        with patch.object(
            common_mod, "Registry", side_effect=RuntimeError("registry boom")
        ):
            with pytest.raises(RuntimeError, match="registry boom"):
                common_mod.exp_authenticate("any_db", "u", "p", None)


class TestExpAuthenticateNotAnOdooDatabase:
    """``exp_authenticate`` returns ``False`` for a reachable non-Odoo database.

    This pins the OTHER half of the no-leak invariant: not the paths where
    ``Registry`` *raises* (covered above), but the path where it *succeeds*
    against a database that exists and connects yet was never initialized by
    Odoo (``postgres``, ``template1``, a bare ``createdb``).  Its registry
    loads the model classes from Python but never loads modules, so
    ``registry.models`` does not contain ``res.users``.

    Without the ``"res.users" not in registry.models`` guard in
    ``exp_authenticate``, ``env["res.users"]`` raises a telltale
    ``KeyError('res.users')`` that an unauthenticated caller could use to tell
    "exists but not an Odoo DB" apart from "does not exist" (``False``) —
    defeating the same enumeration mitigation as the exception-absorption tests.
    All the sibling tests mock ``Registry`` to *raise*, so none of them exercise
    this branch; a refactor deleting the membership check would keep them green.
    """

    def test_missing_res_users_model_returns_false(self, common_mod):
        """A registry whose ``.models`` lacks ``res.users`` collapses to ``False``.

        The fake registry raises if a cursor is ever opened, proving the
        membership check short-circuits *before* any credential work — i.e. the
        ``KeyError`` leak is prevented at the guard, not accidentally masked
        further down the call chain.
        """

        class _NotOdooRegistry:
            # Mirrors the real registry on a bare DB: model classes are present
            # as a mapping, but modules were never loaded, so res.users is absent.
            models = {"ir.model": object()}

            def cursor(self, *args, **kwargs):  # pragma: no cover - must not run
                raise AssertionError(
                    "cursor() must not be opened once res.users is known absent"
                )

        with patch.object(
            common_mod, "Registry", return_value=_NotOdooRegistry()
        ):
            assert common_mod.exp_authenticate("bare_db", "admin", "admin", None) is False


# ---------------------------------------------------------------------------
# Module docstring — must be reachable
# ---------------------------------------------------------------------------


class TestServiceModuleDocstring:
    """The ``odoo.service`` package docstring must be reachable as ``__doc__``.

    Regression: the docstring used to live AFTER the ``from . import ...``
    statements in ``service/__init__.py``, making it a top-level expression
    statement instead of the module docstring.  ``odoo.service.__doc__`` was
    ``None``, breaking ``help(odoo.service)`` and api-doc generators.
    """

    def test_service_package_has_docstring(self):
        import odoo.service  # noqa: PLC0415

        assert odoo.service.__doc__ is not None
        assert "RPC" in odoo.service.__doc__ or "network protocols" in odoo.service.__doc__
