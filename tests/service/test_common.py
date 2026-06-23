"""Pure-pytest tests for ``odoo.service.common``.

Covers the RPC dispatch allowlist — specifically, the regression that
replaced ``globals()`` reflection with an explicit ``_DISPATCH`` dict.

Run with::

    python -m pytest core/tests/service/test_common.py -v
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
    """``dispatch()`` only exposes methods present in ``_DISPATCH``.

    The old ``globals()`` reflection made any module-level ``exp_*`` function
    reachable unauthenticated; the explicit allowlist prevents that.
    """

    def test_allowlist_contains_expected_public_methods(self, common_mod):
        """The three documented RPC methods must be reachable."""
        assert set(common_mod._DISPATCH) == {"login", "authenticate", "version"}

    def test_unknown_method_raises(self, common_mod):
        """A method not in the allowlist must raise, not silently call nothing."""
        with pytest.raises(AttributeError, match="Method not found"):
            common_mod.dispatch("not_a_real_method", [])

    def test_accidental_exp_helper_is_not_reachable(self, common_mod):
        """A module-level ``exp_*`` helper must NOT become a public RPC method.

        Under the old ``globals()`` dispatch it would be callable
        unauthenticated; the allowlist blocks it.
        """

        def exp_accidental_debug_helper():
            return "this should never be reachable via RPC"

        with patch.object(common_mod, "exp_accidental_debug_helper", exp_accidental_debug_helper, create=True):
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

    The connection layer wraps ``getconn`` failures (missing DB, dead PG, bad
    credentials, saturation) in ``odoo.db.PoolError``; if that escaped, an
    attacker could tell a missing DB from an overloaded one, defeating the
    database-enumeration mitigation. ``LookupError`` is no longer caught — it
    never matched a real failure and hid unrelated ``KeyError`` bugs.
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

        The old ``LookupError`` catch also swallowed ``KeyError`` from Registry
        bugs; dropping it lets those surface.
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


# ---------------------------------------------------------------------------
# Module docstring — must be reachable
# ---------------------------------------------------------------------------


class TestServiceModuleDocstring:
    """The ``odoo.service`` package docstring must be reachable as ``__doc__``.

    A docstring placed after the ``from . import ...`` lines becomes a plain
    expression, leaving ``__doc__`` None and breaking ``help()``/api-doc tools.
    """

    def test_service_package_has_docstring(self):
        import odoo.service  # noqa: PLC0415

        assert odoo.service.__doc__ is not None
        assert "RPC" in odoo.service.__doc__ or "network protocols" in odoo.service.__doc__
