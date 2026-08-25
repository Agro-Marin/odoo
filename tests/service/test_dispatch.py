"""``_dispatch``: the one argument-validation policy the RPC tables share.

The defect this replaces was measurable over the wire.  ``/xmlrpc/2/common`` is
``auth="none"``, and ``common.dispatch`` splatted its params into the handler
without checking anything, so an anonymous caller who miscounted arguments was
handed the internal handler's name and signature by CPython::

    login("db", "admin")  -> Fault: TypeError: exp_login() missing 1 required
                                    positional argument: 'password'

``db.dispatch`` checked only the master-password argument and then splatted the
rest.  Two tables behind one door (``odoo/http/helpers.py``), two policies.

These tests pin what the caller is told: the RPC method name, never the
``exp_*`` function behind it.
"""

import pytest

from odoo.service import common
from odoo.service._dispatch import dispatch_table, positional_bounds
from odoo.service.db import rpc


def _no_op(a, b, c=3):
    return (a, b, c)


def _variadic(a, *rest):
    return (a, rest)


def _nullary():
    return "ok"


class TestPositionalBounds:
    def test_required_maximum_and_names(self):
        assert positional_bounds(_no_op) == (2, 3, ("a", "b", "c"))

    def test_var_positional_is_unbounded(self):
        assert positional_bounds(_variadic) == (1, None, ("a",))

    def test_nullary(self):
        assert positional_bounds(_nullary) == (0, 0, ())

    def test_a_wrapped_handler_keeps_its_signature(self):
        """Every ``db`` verb behind ``@check_db_management_enabled`` would
        otherwise introspect as ``(*args, **kwargs)`` and skip the check
        entirely.  The decorator uses ``functools.wraps``, so it does not."""
        assert positional_bounds(rpc.exp_change_admin_password) == (
            1,
            1,
            ("new_password",),
        )


class TestArityIsCheckedBeforeTheSplat:
    def test_too_few_names_the_rpc_method_not_the_handler(self):
        with pytest.raises(TypeError) as exc:
            common.dispatch("login", ["mydb", "admin"])
        message = str(exc.value)
        assert "'login'" in message
        assert "(db, login, password)" in message
        assert "exp_login" not in message

    def test_too_many_names_the_rpc_method_not_the_handler(self):
        with pytest.raises(TypeError) as exc:
            common.dispatch("version", [1])
        assert "'version'" in str(exc.value)
        assert "exp_version" not in str(exc.value)

    def test_unknown_method_still_raises_attribute_error(self):
        with pytest.raises(AttributeError, match="Method not found: nosuch"):
            common.dispatch("nosuch", [])

    def test_variadic_handler_accepts_any_surplus(self):
        table = {"anything": _variadic}
        assert dispatch_table("anything", [1, 2, 3], table) == (1, (2, 3))


class TestLegacyAuthenticateArity:
    """``exp_authenticate`` normalises ``user_agent_env=None`` to ``{}`` in its
    own body, yet demanded the argument positionally -- so a three-argument
    legacy client got a ``TypeError`` instead of the default it was written to
    rely on."""

    def test_three_argument_authenticate_is_accepted(self):
        # An unexposed empty db name short-circuits to False before any I/O;
        # what matters is that arity no longer refuses the call.
        assert common.dispatch("authenticate", ["", "user", "pw"]) is False

    def test_four_argument_authenticate_still_works(self):
        assert common.dispatch("authenticate", ["", "user", "pw", {}]) is False


class TestCredentialStripping:
    def test_missing_master_password_is_named_as_such(self):
        with pytest.raises(TypeError, match="requires a master password"):
            rpc.dispatch("dump", [])

    def test_credential_is_consumed_before_the_arity_check(self, monkeypatch):
        seen = []
        monkeypatch.setitem(rpc._DISPATCH, "dump", lambda *a: seen.append(a))
        monkeypatch.setattr(rpc, "check_super", lambda pw: seen.append(("pw", pw)))
        rpc.dispatch("dump", ["secret", "mydb", "zip"])
        assert seen == [("pw", "secret"), ("mydb", "zip")]

    def test_a_credentialed_method_without_a_checker_refuses_to_run(self):
        called = []
        table = {"danger": lambda *a: called.append(a)}
        with pytest.raises(RuntimeError, match="no check_credential"):
            dispatch_table(
                "danger", ["secret"], table, credentialed=frozenset({"danger"})
            )
        assert not called, "the handler ran without its credential verified"


class TestBothTablesShareOnePolicy:
    @pytest.mark.parametrize(
        ("dispatcher", "method", "params"),
        [
            (common.dispatch, "login", ["only-one"]),
            (rpc.dispatch, "list_lang", [1]),
        ],
    )
    def test_arity_errors_look_the_same_from_either_table(
        self, dispatcher, method, params
    ):
        with pytest.raises(TypeError, match=rf"RPC method '{method}'"):
            dispatcher(method, params)


def test_a_type_checking_only_annotation_does_not_break_introspection():
    """PEP 649 defers annotation evaluation, so a handler annotated with a name
    that only exists under ``TYPE_CHECKING`` -- the style this fork prescribes,
    and the style `service/security.py` now uses -- would raise ``NameError``
    if the bounds lookup evaluated annotations.  It reads kinds and defaults
    only."""

    def handler(session: OnlyUnderTypeChecking, flag: bool = False):  # noqa: F821
        return session

    assert positional_bounds(handler) == (1, 2, ("session", "flag"))
    assert dispatch_table("h", ["x"], {"h": handler}) == "x"
