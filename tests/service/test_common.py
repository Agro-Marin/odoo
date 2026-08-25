"""Pure-pytest tests for ``odoo.service.common``.

Covers the RPC dispatch allowlist — specifically, the regression that
replaced ``globals()`` reflection with an explicit ``_DISPATCH`` dict.

Run with::

    python -m pytest tests/service/test_common.py -v
"""

from unittest.mock import MagicMock, patch

import pytest

from .conftest import fake_pg_cursor


@pytest.fixture(scope="module")
def common_mod():
    """Import ``odoo.service.common`` once per session."""
    import odoo.service.common as mod

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
        with patch.object(
            common_mod,
            "exp_accidental_debug_helper",
            exp_accidental_debug_helper,
            create=True,
        ):
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
# exp_version() — the wire contract
# ---------------------------------------------------------------------------


class TestVersionPayload:
    """``exp_version()`` is an ``auth="none"`` verb every client reads on
    connect, so its key names are a published interface, not an implementation
    detail: dropping or renaming one breaks external callers silently.

    Moved here from ``test_server.py``, which carried the only assertion on
    these keys — the sole unique coverage in a class that otherwise re-tested
    ``dispatch()`` more weakly than the suite above (``pytest.raises(Exception)``
    where this file pins ``AttributeError``).
    """

    @pytest.mark.parametrize(
        "key", ["server_version", "server_version_info", "server_serie"]
    )
    def test_version_keys_are_published(self, common_mod, key):
        assert key in common_mod.exp_version()

    def test_protocol_version_is_pinned(self, common_mod):
        """A bump here is a protocol change; it must be deliberate."""
        assert common_mod.exp_version()["protocol_version"] == 1

    def test_version_follows_a_late_patch_of_odoo_release(self, common_mod):
        """Addons patch ``odoo.release`` after this module is imported --
        `enterprise/web_enterprise/version.py` appends the ``+e`` edition
        marker. Built once at import, the payload kept the pre-patch values and
        reported a version the server is not running, which is why that addon
        also had to re-apply its edit to `RPC_VERSION_1` by hand."""
        import odoo.release

        with (
            patch.object(odoo.release, "version", "19.0-PATCHED+e"),
            patch.object(odoo.release, "version_info", (19, 0, 0, "final", 0, "e")),
        ):
            payload = common_mod.exp_version()
        assert payload["server_version"] == "19.0-PATCHED+e"
        assert payload["server_version_info"] == (19, 0, 0, "final", 0, "e")

        # ...and the payload goes back to tracking release once the patch lifts.
        assert common_mod.exp_version()["server_version"] == odoo.release.version

    def test_rpc_version_1_survives_as_a_snapshot(self, common_mod):
        """The name is public API (`__all__`), so it still resolves -- but as a
        fresh snapshot. Mutating what it returns must not change what the wire
        verb answers; that shared mutable global was the defect."""
        snapshot = common_mod.RPC_VERSION_1
        assert snapshot == common_mod.exp_version()
        snapshot["server_version"] = "tampered"
        assert common_mod.exp_version()["server_version"] != "tampered"

    def test_an_unknown_module_attribute_still_raises(self, common_mod):
        """The module-level ``__getattr__`` must not turn every typo into
        something that resolves."""
        with pytest.raises(AttributeError, match="no attribute 'NoSuchName'"):
            common_mod.NoSuchName


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
        from odoo.db import PoolError

        with patch.object(
            common_mod, "Registry", side_effect=PoolError("pool exhausted")
        ) as registry:
            assert common_mod.exp_authenticate("any_db", "u", "p", None) is False
        # Every test in this class drives ``Registry`` to raise and none observed
        # the name it was called with, so authenticating against a DIFFERENT
        # database than the caller named was invisible: `Registry(db)` ->
        # `Registry("postgres")` passed the whole suite (verified by mutation).
        # One assertion here covers the shared call site.
        registry.assert_called_once_with("any_db")

    def test_psycopg_operational_error_still_returns_false(self, common_mod):
        """Regression-check the surviving catch: bypass paths that don't go
        through the pool (direct ``psycopg.connect`` from migration scripts)
        still raise ``OperationalError`` and must still collapse to ``False``."""
        import psycopg

        with patch.object(
            common_mod, "Registry", side_effect=psycopg.OperationalError("PG down")
        ):
            assert common_mod.exp_authenticate("any_db", "u", "p", None) is False

    def test_invalid_catalog_name_returns_false_not_raise(self, common_mod):
        """ "Database does not exist" must collapse to ``False``, like every other
        connect failure.

        Regression, and a subtle one: the catch used to be
        ``psycopg.OperationalError``, but ``odoo.db.pool`` deliberately
        *translates* a connect-phase failure into its precise SQLSTATE class
        (``_probe_connectable`` / ``_database_absent``, added so an absent DB
        fails fast in any server locale instead of burning the ~30s retry).
        ``InvalidCatalogName`` is a ``ProgrammingError``, NOT an
        ``OperationalError`` — so that improvement silently turned this
        ``auth="none"`` verb into a per-name database EXISTENCE ORACLE:
        a missing DB raised an RPC Fault while an existing one returned
        ``False``.  Measured against a live PG 18 cluster before the fix.
        """
        import psycopg

        assert not issubclass(
            psycopg.errors.InvalidCatalogName, psycopg.OperationalError
        ), "premise of this test: InvalidCatalogName is not an OperationalError"
        with patch.object(
            common_mod,
            "Registry",
            side_effect=psycopg.errors.InvalidCatalogName(
                'database "x" does not exist'
            ),
        ):
            assert common_mod.exp_authenticate("no_such_db", "u", "p", None) is False

    @pytest.mark.parametrize(
        "exc_name", ["InsufficientPrivilege", "InvalidPassword", "TooManyConnections"]
    )
    def test_any_psycopg_error_returns_false(self, common_mod, exc_name):
        """The catch is the whole ``psycopg.Error`` tree, not a hand-kept list.

        Each of these is a different SQLSTATE the pool can surface from a
        connect, and each classifies under a different psycopg base class.  The
        no-enumeration invariant must not depend on someone remembering to add
        the next one.
        """
        import psycopg

        with patch.object(
            common_mod,
            "Registry",
            side_effect=getattr(psycopg.errors, exc_name)("nope"),
        ):
            assert common_mod.exp_authenticate("any_db", "u", "p", None) is False

    def test_unexpected_db_error_is_logged_loudly_even_though_answer_is_false(
        self, common_mod, caplog
    ):
        """Broadening the catch must not make real faults invisible.

        Catching all of ``psycopg.Error`` is what keeps the wire answer uniform,
        but it also swallows a genuine server-side fault — a module raising
        ``ProgrammingError`` while the registry loads, a half-migrated schema.
        The RPC answer stays ``False``; the operator still gets a WARNING.
        """
        import logging

        import psycopg

        with caplog.at_level(logging.DEBUG, logger="odoo.service.common"):
            with patch.object(
                common_mod,
                "Registry",
                side_effect=psycopg.errors.UndefinedTable(
                    "relation ... does not exist"
                ),
            ):
                assert common_mod.exp_authenticate("some_db", "u", "p", None) is False
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings, "an unexpected database error must not vanish at DEBUG"
        assert "unexpected database error" in warnings[0].getMessage()

    @pytest.mark.parametrize(
        "exc_factory",
        [
            lambda: __import__("psycopg").errors.InvalidCatalogName("no such db"),
            lambda: __import__("psycopg").OperationalError("PG down"),
        ],
    )
    def test_routine_connect_failures_stay_quiet(self, common_mod, caplog, exc_factory):
        """A "no such database" probe is attacker-drivable — it must not let an
        unauthenticated caller flood the log at WARNING."""
        import logging

        with caplog.at_level(logging.DEBUG, logger="odoo.service.common"):
            with patch.object(common_mod, "Registry", side_effect=exc_factory()):
                assert common_mod.exp_authenticate("any_db", "u", "p", None) is False
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

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

        with patch.object(common_mod, "Registry", return_value=_NotOdooRegistry()):
            assert (
                common_mod.exp_authenticate("bare_db", "admin", "admin", None) is False
            )


class TestExpAuthenticateNeverServableNames:
    """Cluster-infrastructure names are refused BEFORE ``Registry`` is built.

    ``postgres`` / ``template0`` / ``template1`` and the configured
    ``db_template`` can never be Odoo databases, so no login against them can
    succeed.  ``Registry.new`` does refuse them already — with ``ValueError``
    ("Refusing to build a registry over system or template database"), which is
    neither a ``psycopg.Error`` nor a ``PoolError``.  So it escaped
    ``exp_authenticate`` and these names answered with an RPC ERROR while every
    other name answered ``False`` (measured: ``exp_authenticate("postgres", ...)``
    raised ``ValueError`` before this guard).  Same non-uniform-answer defect as
    the ``InvalidCatalogName`` case, different exception class.

    ``db._rpc_db_exist`` floors exactly these names out of the wire-facing
    ``db_exist``; this is the same floor on the sibling verb.
    """

    @pytest.mark.parametrize("db", ["postgres", "template0", "template1"])
    def test_system_dbs_refused_without_connecting(self, common_mod, db):
        def _must_not_run(*args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError(f"Registry({db!r}) must not be built")

        with patch.object(common_mod, "Registry", side_effect=_must_not_run):
            assert common_mod.exp_authenticate(db, "admin", "admin", None) is False

    def test_unlisted_database_refused_when_database_option_is_set(self, common_mod):
        """``--database`` IS the exposed-database allowlist.

        ``db_filter`` and ``list_dbs`` already give it that meaning; applying it
        here stops an unauthenticated caller from making the server build a
        registry and a pool for a database this instance was never told to
        serve (a shared cluster's other tenants, for instance).
        """
        from odoo.tools import config

        def _must_not_run(*a, **kw):  # pragma: no cover - must not run
            raise AssertionError("Registry must not be built for an unlisted db")

        with (
            config.patch(db_name=["served_db"]),
            patch.object(common_mod, "Registry", side_effect=_must_not_run),
        ):
            assert common_mod.exp_authenticate("other_db", "a", "b", None) is False

    def test_listed_database_still_reaches_the_registry(self, common_mod):
        """The gate must not break real logins: a listed name — and ANY name
        when ``--database`` is unset — still goes through to the registry."""
        from odoo.tools import config

        for options in ({"db_name": []}, {"db_name": ["served_db"]}):
            with (
                config.patch(**options),
                patch.object(
                    common_mod, "Registry", side_effect=RuntimeError("reached")
                ),
            ):
                with pytest.raises(RuntimeError, match="reached"):
                    common_mod.exp_authenticate("served_db", "a", "b", None)

    def test_dbfilter_is_not_applied(self, common_mod):
        """``--db-filter`` maps a HOSTNAME to a database, and ``dispatch_rpc``
        runs inside ``borrow_request()`` which pops the request off the stack —
        so no host is available here.  Applying it would evaluate ``^%h$``
        against an empty host and refuse every RPC login on a virtual-host
        deployment.  An RPC caller names its database explicitly.
        """
        from odoo.tools import config

        with (
            config.patch(dbfilter="^nomatch$", db_name=[]),
            patch.object(common_mod, "Registry", side_effect=RuntimeError("reached")),
        ):
            with pytest.raises(RuntimeError, match="reached"):
                common_mod.exp_authenticate("any_db", "a", "b", None)

    def test_configured_template_refused_without_connecting(self, common_mod):
        """A CUSTOM ``db_template`` (this workspace ships one) is equally unservable."""
        from odoo.tools import config

        def _must_not_run(*args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("Registry(db_template) must not be built")

        with (
            config.patch(db_template="tpl_custom"),
            patch.object(common_mod, "Registry", side_effect=_must_not_run),
        ):
            assert common_mod.exp_authenticate("tpl_custom", "a", "b", None) is False


# ---------------------------------------------------------------------------
# exp_authenticate — hostile argument types
# ---------------------------------------------------------------------------


class TestExpAuthenticateArgumentTypes:
    """Hostile argument TYPES collapse to ``False`` like every other failure.

    ``exp_authenticate`` is reachable with ``auth="none"`` over ``/jsonrpc`` and
    ``/xmlrpc/common``, so the arguments are whatever the caller put on the wire
    — an int, ``None``, a list — not necessarily strings.  The sibling classes
    above are exhaustive about the uniform-answer invariant, but every one of
    them passes well-formed strings and drives the failure through ``Registry``;
    none exercises the type guards that run before it.  Verified by mutation:
    deleting the ``login``/``password`` or ``user_agent_env`` guard left the
    whole 760-test suite green.  Without them a non-``str`` credential reaches
    ``res.users.authenticate`` and a non-``dict`` ``user_agent_env`` reaches the
    ``{**user_agent_env, ...}`` spread, which raises ``TypeError`` — neither a
    ``psycopg.Error`` nor a ``PoolError``, so it escapes the catch as an RPC
    Fault.  That is a distinguishable answer, i.e. the same defect class as the
    ``InvalidCatalogName`` oracle, reached through the argument list instead.

    The ``db`` case is different and the test below is deliberately weaker than
    it looks: ``rpc_db_exposed`` (``_db_helpers.py``, typed ``db_name: object``)
    opens with the identical ``isinstance`` check, so deleting ``exp_authenticate``'s
    own copy is an EQUIVALENT mutation — the answer is still ``False``, one layer
    down.  What is pinned here is therefore the observable behaviour of the
    public verb, not that particular line; it holds whichever layer enforces it,
    and it fails if BOTH are removed.
    """

    @pytest.mark.parametrize("db", [None, 42, b"bytes", ["mydb"], {"db": 1}, ""])
    def test_non_string_or_empty_db_returns_false(self, common_mod, db):
        def _must_not_run(*a, **kw):  # pragma: no cover - must not run
            raise AssertionError(f"Registry({db!r}) must not be built")

        with patch.object(common_mod, "Registry", side_effect=_must_not_run):
            assert common_mod.exp_authenticate(db, "u", "p", None) is False

    @pytest.mark.parametrize(
        ("login", "password"), [(None, "p"), ("u", None), (42, "p"), ("u", ["p"])]
    )
    def test_non_string_credentials_return_false(self, common_mod, login, password):
        def _must_not_run(*a, **kw):  # pragma: no cover - must not run
            raise AssertionError("Registry must not be built for non-str credentials")

        with patch.object(common_mod, "Registry", side_effect=_must_not_run):
            assert common_mod.exp_authenticate("db", login, password, None) is False

    @pytest.mark.parametrize("bad_env", [42, "string", ["list"], (1, 2)])
    def test_non_dict_user_agent_env_returns_false(self, common_mod, bad_env):
        def _must_not_run(*a, **kw):  # pragma: no cover - must not run
            raise AssertionError("Registry must not be built for a non-dict env")

        with patch.object(common_mod, "Registry", side_effect=_must_not_run):
            assert common_mod.exp_authenticate("db", "u", "p", bad_env) is False

    def test_none_user_agent_env_is_still_accepted(self, common_mod):
        """``None`` is the documented "no metadata" value — ``exp_login`` passes
        it on every call — and must NOT be refused by the dict guard."""
        with patch.object(common_mod, "Registry", side_effect=RuntimeError("reached")):
            with pytest.raises(RuntimeError, match="reached"):
                common_mod.exp_authenticate("db", "u", "p", None)


class TestExpAuthenticateCredentialOutcome:
    """The paths where the registry LOADS and credentials are actually checked.

    Everything else in this file drives ``Registry`` to raise or to lack
    ``res.users``; both short-circuit before a cursor is ever opened (the
    not-an-Odoo-database test asserts exactly that).  So the function's primary
    job — hand the credential to ``res.users.authenticate`` and return its uid,
    or ``False`` when it refuses — was pinned by nothing.  Verified by mutation:
    changing ``except AccessDenied: return False`` to return ``999`` left the
    suite green, so a wrong password could have started answering with a
    truthy value without any test noticing.
    """

    @staticmethod
    def _registry(authenticate):
        cursor = fake_pg_cursor()
        users = MagicMock()
        users.authenticate = authenticate
        registry = MagicMock()
        registry.models = {"res.users": object()}
        registry.cursor.return_value = cursor
        return registry, users

    def test_valid_credentials_return_the_uid(self, common_mod):
        registry, users = self._registry(lambda credential, env: {"uid": 7})
        env = MagicMock()
        env.__getitem__ = MagicMock(return_value=users)
        with (
            patch.object(common_mod, "Registry", return_value=registry),
            patch("odoo.api.Environment", return_value=env),
        ):
            assert common_mod.exp_authenticate("db", "alice", "pw", None) == 7

    def test_the_credential_dict_is_a_password_login(self, common_mod):
        """The wire contract with ``res.users.authenticate``: a ``password``-type
        credential carrying the caller's login, marked non-interactive."""
        seen = {}

        def authenticate(credential, env):
            seen["credential"] = credential
            seen["env"] = env
            return {"uid": 1}

        registry, users = self._registry(authenticate)
        env = MagicMock()
        env.__getitem__ = MagicMock(return_value=users)
        with (
            patch.object(common_mod, "Registry", return_value=registry),
            patch("odoo.api.Environment", return_value=env),
        ):
            common_mod.exp_authenticate("db", "alice", "s3cret", {"base_location": "x"})
        assert seen["credential"] == {
            "login": "alice",
            "password": "s3cret",
            "type": "password",
        }
        assert seen["env"]["interactive"] is False
        assert seen["env"]["base_location"] == "x"

    def test_wrong_password_returns_false_not_a_truthy_value(self, common_mod):
        from odoo.exceptions import AccessDenied

        def authenticate(credential, env):
            raise AccessDenied

        registry, users = self._registry(authenticate)
        env = MagicMock()
        env.__getitem__ = MagicMock(return_value=users)
        with (
            patch.object(common_mod, "Registry", return_value=registry),
            patch("odoo.api.Environment", return_value=env),
        ):
            result = common_mod.exp_authenticate("db", "alice", "wrong", None)
        assert result is False

    def test_an_unexpected_error_from_authenticate_still_propagates(self, common_mod):
        """Only ``AccessDenied`` is collapsed here.  A bug inside the credential
        check must not be laundered into "wrong password"."""

        def authenticate(credential, env):
            raise RuntimeError("bug in the auth provider")

        registry, users = self._registry(authenticate)
        env = MagicMock()
        env.__getitem__ = MagicMock(return_value=users)
        with (
            patch.object(common_mod, "Registry", return_value=registry),
            patch("odoo.api.Environment", return_value=env),
        ):
            with pytest.raises(RuntimeError, match="bug in the auth provider"):
                common_mod.exp_authenticate("db", "alice", "pw", None)


class TestServiceModuleDocstring:
    """The ``odoo.service`` package docstring must be reachable as ``__doc__``.

    Regression: the docstring used to live AFTER the ``from . import ...``
    statements in ``service/__init__.py``, making it a top-level expression
    statement instead of the module docstring.  ``odoo.service.__doc__`` was
    ``None``, breaking ``help(odoo.service)`` and api-doc generators.
    """

    def test_service_package_has_docstring(self):
        import odoo.service

        assert odoo.service.__doc__ is not None
        assert (
            "RPC" in odoo.service.__doc__ or "network protocols" in odoo.service.__doc__
        )
