"""
The module :mod:`odoo.tests.common` provides unittest test cases and a few
helpers and classes to write tests.

"""

import contextlib
import difflib
import importlib
import inspect
import logging
import pprint
import re
import sys
import threading
import traceback
import unittest
import warnings
from collections import defaultdict, deque
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from functools import partial, wraps
from itertools import zip_longest
from typing import TYPE_CHECKING, Any, cast
from unittest import TestResult
from unittest.mock import Mock, _patch, patch
from urllib.parse import urlsplit

import freezegun
import psutil
import requests
from lxml import etree, html
from requests import PreparedRequest, Session
from werkzeug.exceptions import BadRequest

import odoo.cli
import odoo.http
import odoo.models
import odoo.orm.runtime
from odoo import api
from odoo.db import Cursor, Savepoint
from odoo.db.utils import seed_planner_stats
from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.modules.registry import DummyRLock, Registry
from odoo.tools import (
    SQL,
    DotDict,
    config,
    float_compare,
    mute_logger,
    profiler,
)
from odoo.tools.cache import _COUNTERS
from odoo.tools.mail import single_email_re
from odoo.tools.misc import lower_logging
from odoo.tools.password import CryptContext
from odoo.tools.xml_utils import _validate_xml

from . import case
from .browser import DEFAULT_SUCCESS_SIGNAL, ChromeBrowser, ChromeBrowserException
from .cursor import TestCursor
from .utils import HOST, env_int, get_db_name, save_test_file

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable

    # only referenced by the Approx annotation below; a runtime import would
    # make the framework's import drag in addon code (see conventions.md)
    import odoo.addons.base
    from .result import OdooTestResult


# Public API re-exported as `odoo.tests` (see tests/__init__.py).  Without
# this, the star-import used to republish every stdlib module imported above
# (odoo.tests.json, odoo.tests.os, ...).
# `Command`, `mute_logger` and `patch` are sanctioned convenience re-exports
# (odoo.fields / odoo.tools / unittest.mock), widely imported from odoo.tests.
__all__ = [
    "ADMIN_USER_ID",
    "DEFAULT_SUCCESS_SIGNAL",
    "HOST",
    "TEST_CURSOR_COOKIE_NAME",
    "Approx",
    "BaseCase",
    "BlockedRequest",
    "ChromeBrowser",
    "ChromeBrowserException",
    "Command",
    "HttpCase",
    "JsonRpcException",
    "Like",
    "Opener",
    "RecordCapturer",
    "SingleTransactionCase",
    "TransactionCase",
    "Transport",
    "WhitespaceInsensitive",
    "can_import",
    "freeze_time",
    "get_cache_key_counter",
    "get_db_name",
    "loaded_demo_data",
    "mute_logger",
    "new_test_user",
    "no_retry",
    "patch",
    "release_test_lock",
    "save_test_file",
    "skip_if_dev_mode",
    "standalone",
    "standalone_tests",
    "tagged",
    "test_xsd",
    "users",
    "warmup",
]

_logger = logging.getLogger(__name__)
if odoo.cli.COMMAND in ("server", "start") and not config["test_enable"]:
    _logger.error(
        "Importing test framework, avoid importing from business modules and when not running in test mode",
        stack_info=True,
    )
else:
    _logger.info(
        "Importing test framework",
        stack_info=_logger.isEnabledFor(logging.DEBUG),
    )


def get_cache_key_counter(bound_method, *args, **kwargs):
    """Return the cache, key and stat counter for the given call.

    Test utility for inspecting ORM cache internals (hit/miss counters).
    """
    model = bound_method.__self__
    ormcache_instance = bound_method.__cache__
    cache = model.pool._Registry__caches[ormcache_instance.cache_name]
    key = ormcache_instance.key(model, *args, **kwargs)
    counter = _COUNTERS[model.pool.db_name, ormcache_instance.method]
    return cache, key, counter


# Useless constant, tests are aware of the content of demo data
ADMIN_USER_ID = api.SUPERUSER_ID

TEST_CURSOR_COOKIE_NAME = "test_request_key"


def skip_if_dev_mode(*flags: str) -> None:
    """Skip the running test when ``--dev`` disables what it asserts.

    Several caches are deliberately switched off in dev mode so edits are
    picked up live: the QWeb template-compile and ir.rule domain ormcaches key
    on ``"xml" not in config["dev_mode"]``, and QWeb error messages gain the
    generated source when ``"qweb"`` is set. A test pinning the *cached*
    behaviour is therefore meaningless on a dev-mode server — it must skip
    with a reason, not fail with a confusing diff, which is what a developer
    running the suite against their own ``--dev=xml,qweb`` server used to get.

    :param flags: ``--dev`` flags that invalidate the assertion (e.g. ``xml``).
    """
    dev_mode = config["dev_mode"]
    if active := [flag for flag in flags if flag in dev_mode]:
        raise unittest.SkipTest(
            f"--dev={','.join(active)} disables the behaviour under test"
        )


standalone_tests = defaultdict(list)


class RegistryRLock(threading._RLock):
    # Deliberately subclasses the *pure-Python* RLock: the C implementation
    # returned by the threading.RLock() factory does not expose its recursion
    # count, which the framework introspects for lock-balance warnings
    # (TransactionCase.setUp).  Slower than the C lock, but it is taken once
    # per HTTP request during tests, not on any hot path.
    @property
    def count(self) -> int:
        """Expose the private reentrant lock acquisition count."""
        return self._count  # Expose private attribute


# The lock should only be released when new test cursors are meant to be opened.
# Further filtering on cursors can be done by extending `assertCanOpenTestCursor`.
_registry_test_lock = RegistryRLock()
_registry_test_lock.acquire()


@contextmanager
def release_test_lock() -> Generator[None]:
    """Release the test lock in a context manager; reacquire when done."""
    try:
        _registry_test_lock.release()
        yield
    finally:
        if not _registry_test_lock.acquire(timeout=60):
            tag = odoo.modules.module.current_test.canonical_tag
            # sys.exit, not the site-provided exit() builtin: same SystemExit
            # semantics, but always available (python -S, frozen builds)
            sys.exit(f"Could not re-acquire the registry lock during {tag}, exiting...")


def standalone(*tags: str) -> Callable[[Callable], Callable]:
    """Decorator for standalone test functions, mainly for tests that install,
    upgrade or uninstall modules (forbidden in regular test cases). Registers the
    function under the given ``tags`` and its Odoo module name.
    """

    def register(func: Callable) -> Callable:
        # register func by odoo module name
        if func.__module__.startswith("odoo.addons."):
            module = func.__module__.split(".")[2]
            standalone_tests[module].append(func)
        # register func with aribitrary name, if any
        for tag in tags:
            standalone_tests[tag].append(func)
        standalone_tests["all"].append(func)
        return func

    return register


def test_xsd(url=None, path=None, skip=False):
    """Decorate a test method returning XML documents to validate them
    against the XSD at ``url`` or ``path``.

    ``skip`` disables the whole test as *skipped* (pass a reason string).
    It used to make the test silently pass without running its body, which
    hid disabled validations from test reports.
    """

    def decorator(func):
        @wraps(func)
        def wrapped_f(self, *args, **kwargs):
            if skip:
                raise unittest.SkipTest(
                    skip if isinstance(skip, str) else "XSD validation disabled"
                )
            xmls = func(self, *args, **kwargs)
            _validate_xml(self.env, url, path, xmls)

        return wrapped_f

    return decorator


def new_test_user(env, login="", groups="base.group_user", context=None, **kwargs):
    """Create a new test user given its login and groups (a comma-separated list
    of xml ids). Kwargs are propagated to ``create`` to further customize the user.

    The ``context`` parameter customizes the environment used for creation, e.g.
    to force a specific behavior or simplify record creation (such as mail-related
    context keys in mail tests to speed up record creation).

    Some specific fields are automatically filled to avoid issues

     * group_ids: it is filled using groups function parameter;
     * name: "login (groups)" by default as it is required;
     * email: it is either the login (if it is a valid email) or a generated
       string 'x.x@example.com' (x being the first login letter). This is due
       to email being required for most odoo operations;
    """
    if not login:
        raise ValueError("New users require at least a login")
    if not groups:
        raise ValueError("New users require at least user groups")
    if context is None:
        context = {}

    group_ids = [
        Command.set(
            kwargs.pop("group_ids", False)
            or [env.ref(g.strip()).id for g in groups.split(",")]
        )
    ]
    create_values = dict(kwargs, login=login, group_ids=group_ids)
    # automatically generate a name as "Login (groups)" to ease user comprehension
    if not create_values.get("name"):
        create_values["name"] = f"{login} ({groups})"
    # automatically give a password equal to login
    if not create_values.get("password"):
        create_values["password"] = login + "x" * (8 - len(login))
    # generate email if not given as most test require an email
    if "email" not in create_values:
        if single_email_re.match(login):
            create_values["email"] = login
        else:
            create_values["email"] = f"{login[0]}.{login[0]}@example.com"
    # ensure company_id + allowed company constraint works if not given at create
    if "company_id" in create_values and "company_ids" not in create_values:
        create_values["company_ids"] = [(4, create_values["company_id"])]

    return env["res.users"].with_context(**context).create(create_values)


def loaded_demo_data(env: api.Environment) -> bool:
    """Return whether demo data is loaded in the given environment."""
    return bool(env.ref("base.user_demo", raise_if_not_found=False))


class RecordCapturer:
    """Context manager that captures records created within its scope."""

    def __init__(self, model: Any, domain: list | None = None) -> None:
        self._model = model
        self._domain = domain or []

    def __enter__(self) -> RecordCapturer:
        self._before = self._model.search(self._domain, order="id")
        self._after = None
        return self

    def __exit__(
        self, exc_type: type | None, exc_value: BaseException | None, exc_traceback: Any
    ) -> None:
        if exc_type is None:
            self._after = self._model.search(self._domain, order="id") - self._before

    @property
    def records(self) -> Any:
        """Return the records created within this context."""
        if self._after is None:
            return self._model.search(self._domain, order="id") - self._before
        return self._after


def _enter_context(cm: Any, addcleanup: Callable) -> Any:
    """Enter a context manager and register its __exit__ as a cleanup function."""
    # We look up the special methods on the type to match the with
    # statement.
    cls = type(cm)
    try:
        enter = cls.__enter__
        exit = cls.__exit__
    except AttributeError:
        raise TypeError(
            f"'{cls.__module__}.{cls.__qualname__}' object does not support the context manager protocol"
        ) from None
    result = enter(cm)
    addcleanup(exit, cm, None, None, None)
    return result


def _normalize_arch_for_assert(arch_string: str, parser_method: str = "xml") -> str:
    """Normalize XML arch for assertion comparison.

    Removes blank text and pretty-prints the output.

    :param arch_string: the string representing an XML arch
    :param parser_method: which lxml.Parser class to use — ``"xml"`` or ``"html"``
    :return: the normalized arch
    """
    if parser_method == "xml":
        Parser = etree.XMLParser
    elif parser_method == "html":
        Parser = etree.HTMLParser
    else:
        raise ValueError(
            f"parser_method must be 'xml' or 'html', got {parser_method!r}"
        )
    parser = Parser(remove_blank_text=True)
    arch_string = etree.fromstring(arch_string, parser=parser)
    return etree.tostring(arch_string, pretty_print=True, encoding="unicode")


class BlockedRequest(requests.exceptions.ConnectionError):
    pass


_super_send = requests.Session.send


class BaseCase(case.TestCase):
    """Subclass of TestCase for Odoo-specific code. This class is abstract and
    expects self.registry, self.cr and self.uid to be initialized by subclasses.
    """

    registry: Registry = None
    env: api.Environment = None
    cr: Cursor = None

    def __init_subclass__(cls) -> None:
        """Assign default test tags ``standard`` and ``at_install`` to test
        cases not having them. Also sets ``test_module``, which tag
        selection (``TagsSelector.check``) matches ``/module`` specs against.
        """
        super().__init_subclass__()
        if cls.__module__.startswith("odoo.addons."):
            if getattr(cls, "test_tags", None) is None:
                cls.test_tags = {"standard", "at_install"}
            cls.test_module = cls.__module__.split(".")[2]

    longMessage = (
        True  # more verbose error message by default: https://www.odoo.com/r/Vmh
    )
    warm = True  # False during warm-up phase (see :func:`warmup`)

    # env_int: an empty-but-set variable (common in CI) must not kill this
    # class body — and with it every `import odoo.tests` — with ValueError.
    _tests_run_count = env_int("ODOO_TEST_FAILURE_RETRIES", 0) + 1

    _registry_patched = False
    _registry_readonly_enabled = True
    test_cursor_lock_timeout: int = 20

    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        self.addTypeEqualityFunc(etree._Element, self.assertTreesEqual)
        self.addTypeEqualityFunc(html.HtmlElement, self.assertTreesEqual)
        if methodName != "runTest":
            self.test_tags = self.test_tags | set(
                self.get_method_additional_tags(getattr(self, methodName))
            )

    @classmethod
    def _request_handler(cls, s: Session, r: PreparedRequest, /, **kw):
        # allow localhost requests
        # TODO: also check port?
        url = urlsplit(r.url)
        timeout = kw.get("timeout")
        if timeout and timeout < 10:
            _logger.getChild("requests").info(
                "request %s with timeout %s increased to 10s during tests",
                url,
                timeout,
            )
            kw["timeout"] = 10
        if url.hostname in (HOST, "localhost"):
            return _super_send(s, r, **kw)
        if url.scheme == "file":
            return _super_send(s, r, **kw)

        _logger.getChild("requests").info(
            "Blocking un-mocked external HTTP request %s %s", r.method, r.url
        )
        raise BlockedRequest(f"External requests verboten (was {r.method} {r.url})")

    def run(self, result: OdooTestResult) -> None:  # type: ignore[override]
        testMethod = getattr(self, self._testMethodName)

        if getattr(testMethod, "_retry", True) and getattr(self, "_retry", True):
            tests_run_count = self._tests_run_count
        else:
            tests_run_count = 1
            _logger.info("Auto retry disabled for %s", self)

        for retry in range(tests_run_count):
            result.had_failure = False  # reset in case of retry without soft_fail
            if retry:
                _logger.runbot(f"Retrying a failed test: {self}")
            if retry < tests_run_count - 1:
                with (
                    warnings.catch_warnings(),
                    result.soft_fail(),
                    lower_logging(25, logging.INFO) as quiet_log,
                ):
                    super().run(cast("TestResult", result))
                if not (result.had_failure or quiet_log.had_error_log):
                    break
            else:  # last try
                super().run(cast("TestResult", result))
                if not result.wasSuccessful() and BaseCase._tests_run_count != 1:
                    _logger.runbot("Disabling auto-retry after a failed test")
                    BaseCase._tests_run_count = 1

    @classmethod
    def setUpClass(cls) -> None:
        def check_remaining_processes() -> None:
            current_process = psutil.Process()
            children = current_process.children(recursive=False)
            for child in children:
                _logger.warning("A child process was found, terminating it: %s", child)
                child.terminate()
            psutil.wait_procs(
                children, timeout=10
            )  # mainly to avoid a zombie process that would be logged again at the end.

        cls.addClassCleanup(check_remaining_processes)

        def check_remaining_patchers():
            for patcher in _patch._active_patches:
                _logger.warning(
                    "A patcher (targeting %s.%s) was remaining active at the end of %s, disabling it...",
                    patcher.target,
                    patcher.attribute,
                    cls.__name__,
                )
                patcher.stop()

        cls.addClassCleanup(check_remaining_patchers)

        def close_sass():
            """Shut down the dart:sass subprocess before child-process check."""
            try:
                from odoo.tools.sass_embedded import close_sass_compiler

                close_sass_compiler()
            except ImportError:
                pass

        cls.addClassCleanup(close_sass)

        def close_esm_lexer():
            """Shut down the node ESM-lexer worker before child-process check.

            Same rationale as `close_sass`: the worker is an intentional
            long-lived child of the asset pipeline, so leaving it to the leak
            check turned every browser-test class into a spurious "A child
            process was found, terminating it: node-MainThread" warning.
            """
            try:
                from odoo.tools.assets.esm_lexer import close_lexer_worker

                close_lexer_worker()
            except ImportError:
                pass

        cls.addClassCleanup(close_esm_lexer)
        super().setUpClass()
        if "standard" in cls.test_tags or "click_all" in cls.test_tags:
            # patch.object stores the value via setattr; an already-bound
            # classmethod isn't re-bound on attribute access, so it would never
            # receive the Session as `s`. A lambda binds and forwards it correctly.
            # pylint: disable=unnecessary-lambda

            patcher = patch.object(
                requests.sessions.Session,
                "send",
                lambda s, r, **kw: cls._request_handler(s, r, **kw),  # noqa: PLW0108  # lambda binds the patched Session as `s`
            )
            patcher.start()
            cls.addClassCleanup(patcher.stop)

    def setUp(self) -> None:
        super().setUp()
        self.http_request_key: str = ""
        self.http_request_allow_all: bool = False

    def cursor(self) -> Cursor:
        """Return a new cursor from the test registry."""
        return self.registry.cursor()

    @property
    def uid(self):
        """Get the current uid."""
        return self.env.uid

    @uid.setter
    def uid(self, user):
        """Set the uid by changing the test's environment."""
        self.env = self.env(user=user)
        # set the updated environment as the default one
        self.env.transaction.default_env = self.env

    def ref(self, xid: str) -> int:
        """Return database ID for the provided :term:`external identifier`.

        Shortcut for ``_xmlid_lookup``.

        :param xid: fully-qualified :term:`external identifier`, in the form
                    :samp:`{module}.{identifier}`
        :raise: ValueError if not found
        :returns: registered id
        """
        return self.browse_ref(xid).id

    def browse_ref(self, xid: str) -> Any:
        """Return a record object for the provided :term:`external identifier`.

        :param xid: fully-qualified :term:`external identifier`, in the form
                    :samp:`{module}.{identifier}`
        :raise: ValueError if not found
        :returns: :class:`~odoo.models.BaseModel`
        """
        assert "." in xid, (
            "this method requires a fully qualified parameter, in the following form: 'module.identifier'"
        )
        return self.env.ref(xid)

    def patch(self, obj: Any, key: str, val: Any) -> None:
        """Do the patch ``setattr(obj, key, val)``, and prepare cleanup."""
        patcher = patch.object(obj, key, val)  # this is unittest.mock.patch
        patcher.start()
        self.addCleanup(patcher.stop)

    @classmethod
    def classPatch(cls, obj: Any, key: str, val: Any) -> None:
        """Do the patch ``setattr(obj, key, val)``, and prepare cleanup."""
        patcher = patch.object(obj, key, val)  # this is unittest.mock.patch
        patcher.start()
        cls.addClassCleanup(patcher.stop)

    def startPatcher(self, patcher: Any) -> Any:
        """Start a patcher and register its stop as a cleanup."""
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    @classmethod
    def startClassPatcher(cls, patcher: Any) -> Any:
        """Start a class-level patcher and register its stop as a class cleanup."""
        mock = patcher.start()
        cls.addClassCleanup(patcher.stop)
        return mock

    def enterContext(self, cm: Any) -> Any:
        """Enter the supplied context manager.

        If successful, also adds its __exit__ method as a cleanup
        function and returns the result of the __enter__ method.
        """
        return _enter_context(cm, self.addCleanup)

    @classmethod
    def enterClassContext(cls, cm: Any) -> Any:
        """Same as enterContext, but class-wide."""
        return _enter_context(cm, cls.addClassCleanup)

    @contextmanager
    def with_user(self, login: str) -> Generator[None]:
        """Change user for a given test, like with self.with_user() ..."""
        old_uid = self.uid
        old_env = self.env
        try:
            user = self.env["res.users"].sudo().search([("login", "=", login)])
            assert user, f"Login {login} not found"
            # switch user (the uid setter rebuilds self.env and the
            # transaction's default_env)
            self.uid = user.id
            yield
        finally:
            # back
            self.uid = old_uid
            self.env = old_env

    @contextmanager
    def debug_mode(self) -> Generator[None]:
        """Enable the effects of debug mode (in particular for group ``base.group_no_one``)."""
        request = Mock(
            httprequest=Mock(host="localhost"),
            db=self.env.cr.dbname,
            env=self.env,
            session=DotDict(odoo.http.get_default_session(), debug="1"),
        )
        try:
            self.env.flush_all()
            self.env.invalidate_all()
            odoo.http._request_stack.push(request)
            yield
            self.env.flush_all()
            self.env.invalidate_all()
        finally:
            popped_request = odoo.http._request_stack.pop()
            if popped_request is not request:
                raise Exception("Wrong request stack cleanup.")

    @contextmanager
    def _assertRaises(
        self,
        exception: type[BaseException] | tuple[type[BaseException], ...],
        *,
        msg: str | None = None,
    ) -> Generator[Any]:
        """Context manager that clears the environment upon failure."""
        with ExitStack() as init:
            if self.env:
                init.enter_context(self.env.cr.savepoint())
                # exception may be a class or a tuple of classes; issubclass
                # rejects a tuple as its first argument, so handle each form.
                if isinstance(exception, tuple):
                    clear_cache = any(issubclass(exc, AccessError) for exc in exception)
                else:
                    clear_cache = issubclass(exception, AccessError)
                if clear_cache:
                    # The savepoint() above calls flush(), which leaves the
                    # record cache with lots of data.  This can prevent
                    # access errors to be detected. In order to avoid this
                    # issue, we clear the cache before proceeding.
                    self.env.cr.clear()

            with ExitStack() as inner:
                cm = inner.enter_context(super().assertRaises(exception, msg=msg))
                # *moves* the cleanups from init to inner, this ensures the
                # savepoint gets rolled back when `yield` raises `exception`,
                # but still allows the initialisation to be protected *and* not
                # interfered with by `assertRaises`.
                inner.push(init.pop_all())

                yield cm

    def assertRaises(
        self,
        exception: type[BaseException],
        func: Callable | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Assert that an exception is raised, clearing the env on failure."""
        if func:
            with self._assertRaises(exception):
                func(*args, **kwargs)
        else:
            return self._assertRaises(exception, **kwargs)
        return None

    def _patchExecute(self, actual_queries, flush=True):
        Cursor_execute = Cursor.execute

        def execute(self, query, params=None, log_exceptions=None):
            actual_queries.append(query.code if isinstance(query, SQL) else query)
            return Cursor_execute(self, query, params, log_exceptions)

        if flush:
            self.env.flush_all()
            self.env.cr.flush()

        with (
            patch("odoo.db.Cursor.execute", execute),
            patch.object(self.env.registry, "unaccent", lambda x: x),
        ):
            yield actual_queries
            if flush:
                self.env.flush_all()
                self.env.cr.flush()

    @staticmethod
    def _normalize_query(query: str) -> str:
        """Normalize a query for comparison: lowercase, strip whitespace,
        and collapse value tuples ``(%s,%s,...,%s)`` (possibly containing
        ``DEFAULT``) to ``(%s)`` so that assertions are independent of the
        number of parameters per row."""
        normalized = "".join(query.lower().split())
        return re.sub(r"\((?:%s|default)(?:,(?:%s|default))*\)", "(%s)", normalized)

    @contextmanager
    def assertQueries(
        self, expected: list[str], flush: bool = True
    ) -> Generator[list[str]]:
        """Check the queries made by the current cursor. ``expected`` is a list
        of strings representing the expected queries being made. Query strings
        are matched against each other, ignoring case and whitespaces.
        """
        actual_queries = []

        yield from self._patchExecute(actual_queries, flush)

        if not self.warm:
            return

        self.assertEqual(
            len(actual_queries),
            len(expected),
            "\n---- actual queries:\n%s\n---- expected queries:\n%s"
            % (
                "\n".join(actual_queries),
                "\n".join(expected),
            ),
        )
        for actual_query, expect_query in zip(actual_queries, expected, strict=False):
            self.assertEqual(
                self._normalize_query(actual_query),
                self._normalize_query(expect_query),
                "\n---- actual query:\n%s\n---- not like:\n%s"
                % (actual_query, expect_query),
            )

    @contextmanager
    def assertQueriesContain(
        self, expected: list[str], flush: bool = True
    ) -> Generator[list[str]]:
        """Check the queries made by the current cursor. ``expected`` is a list
        of strings representing the expected queries being made.

        Despite the name this is not a subset check: exactly ``len(expected)``
        queries must run, and ``expected[i]`` must be *contained in* the i-th
        actual query (ignoring case and whitespace) — use it over
        :meth:`assertQueries` when only fragments of each query matter.
        """
        actual_queries = []

        yield from self._patchExecute(actual_queries, flush)

        if not self.warm:
            return

        self.assertEqual(
            len(actual_queries),
            len(expected),
            "\n---- actual queries:\n%s\n---- expected queries:\n%s"
            % (
                "\n".join(actual_queries),
                "\n".join(expected),
            ),
        )
        for actual_query, expect_query in zip(actual_queries, expected, strict=False):
            self.assertIn(
                self._normalize_query(expect_query),
                self._normalize_query(actual_query),
                "\n---- actual query:\n%s\n---- doesn't contain:\n%s"
                % (actual_query, expect_query),
            )

    @contextmanager
    def assertQueryCount(
        self, default: int = 0, flush: bool = True, **counters: int
    ) -> Generator[None]:
        """Context manager that counts queries. It may be invoked either with
        one value, or with a set of named arguments like ``login=value``::

            with self.assertQueryCount(42):
                ...

            with self.assertQueryCount(admin=3, demo=5):
                ...

        The second form is convenient when used with :func:`users`.
        """
        if self.warm:
            # mock random in order to avoid random bus gc
            with patch("random.random", lambda: 1):
                login = self.env.user.login
                expected = counters.get(login, default)
                if flush:
                    self.env.flush_all()
                    self.env.cr.flush()
                count0 = self.cr.sql_log_count
                yield
                if flush:
                    self.env.flush_all()
                    self.env.cr.flush()
                count = self.cr.sql_log_count - count0
                if count != expected:
                    # add some info on caller to allow semi-automatic update of query count
                    _frame, filename, linenum, funcname, _lines, _index = (
                        inspect.stack()[2]
                    )
                    filename = filename.replace("\\", "/")
                    if "/odoo/addons/" in filename:
                        filename = filename.rsplit("/odoo/addons/", 1)[1]
                    if count > expected:
                        # add a subtest in order to continue the test_method in case of failures
                        with self.subTest():
                            self.fail(
                                "Query count more than expected for user %s: %d > %d in %s at %s:%s"
                                % (
                                    login,
                                    count,
                                    expected,
                                    funcname,
                                    filename,
                                    linenum,
                                )
                            )
                    else:
                        logger = logging.getLogger(type(self).__module__)
                        msg = "Query count less than expected for user %s: %d < %d in %s at %s:%s"
                        logger.info(
                            msg,
                            login,
                            count,
                            expected,
                            funcname,
                            filename,
                            linenum,
                        )
        else:
            # flush before and after during warmup, in order to reproduce the
            # same operations, otherwise the caches might not be ready!
            if flush:
                self.env.flush_all()
                self.env.cr.flush()
            yield
            if flush:
                self.env.flush_all()
                self.env.cr.flush()

    def assertRecordValues(
        self,
        records: odoo.models.BaseModel,
        expected_values: list[dict],
        *,
        field_names: Iterable[str] | None = None,
    ) -> None:
        """Compare a recordset element-by-element (by index) with a list of dicts
        of expected values. Order matters.

        .. note::

            - ``None`` expected values can be used for empty fields.
            - x2many fields are expected by ids (so the expected value should be
              a ``list[int]``
            - many2one fields are expected by id (so the expected value should
              be an ``int``

        :param records: The records to compare.
        :param expected_values: Items to check the ``records`` against.
        :param field_names: list of fields to check during comparison, if
                            unspecified all expected_values must have the same
                            keys and all are checked
        """
        if not field_names:
            field_names = expected_values[0].keys()
            for i, v in enumerate(expected_values):
                self.assertEqual(
                    v.keys(),
                    field_names,
                    f"All expected values must have the same keys, found differences between records 0 and {i}",
                )

        expected_reformatted = []
        for vs in expected_values:
            r = {}
            for f in field_names:
                t = records._fields[f].type
                if t in ("one2many", "many2many"):
                    r[f] = sorted(vs[f])
                elif t == "float":
                    r[f] = float(vs[f])
                elif t == "integer":
                    r[f] = int(vs[f])
                elif vs[f] is None:
                    r[f] = False
                else:
                    r[f] = vs[f]
            expected_reformatted.append(r)

        record_reformatted = []
        for record in records:
            r = {}
            for field_name in field_names:
                record_value = record[field_name]
                match record._fields[field_name]:
                    case odoo.fields.Many2one():
                        record_value = record_value.id
                    case odoo.fields.One2many() | odoo.fields.Many2many():
                        record_value = sorted(record_value.ids)
                    case odoo.fields.Float() as field if digits := field.get_digits(
                        record.env
                    ):
                        record_value = Approx(record_value, digits[1], decorate=False)
                    case odoo.fields.Monetary() as field if (
                        currency_field_name := field.get_currency_field(record)
                    ):
                        # don't round if there's no currency set
                        if c := record[currency_field_name]:
                            record_value = Approx(record_value, c, decorate=False)

                r[field_name] = record_value
            record_reformatted.append(r)

        try:
            self.assertSequenceEqual(
                expected_reformatted, record_reformatted, seq_type=list
            )
            return
        except AssertionError as e:
            standardMsg, _, diffMsg = str(e).rpartition("\n")
            if "self.maxDiff" not in diffMsg:
                raise
            # move out of handler to avoid exception chaining

        diffMsg = "".join(
            difflib.unified_diff(
                pprint.pformat(expected_reformatted).splitlines(keepends=True),
                pprint.pformat(record_reformatted).splitlines(keepends=True),
                fromfile="expected",
                tofile="records",
            )
        )
        self.fail(self._formatMessage(None, standardMsg + "\n" + diffMsg))

    # turns out this thing may not be quite as useful as we thought...
    def assertItemsEqual(self, a: Any, b: Any, msg: str | None = None) -> None:
        """Assert that two sequences contain the same elements."""
        self.assertCountEqual(a, b, msg=msg)

    def assertTreesEqual(self, n1: Any, n2: Any, msg: str | None = None) -> None:
        """Assert two lxml element trees are structurally equal."""
        self.assertIsNotNone(n1, msg)
        self.assertIsNotNone(n2, msg)
        self.assertEqual(n1.tag, n2.tag, msg)
        # Because lxml.attrib is an ordereddict for which order is important
        # to equality, even though *we* don't care
        self.assertEqual(dict(n1.attrib), dict(n2.attrib), msg)
        self.assertEqual((n1.text or "").strip(), (n2.text or "").strip(), msg)
        self.assertEqual((n1.tail or "").strip(), (n2.tail or "").strip(), msg)

        for c1, c2 in zip_longest(n1, n2):
            self.assertTreesEqual(c1, c2, msg)

    def _assertXMLEqual(
        self, original: str, expected: str, parser: str = "xml"
    ) -> None:
        """Assert that two XML arch strings are equal after normalization.

        :param original: the xml arch to test
        :param expected: the xml arch of reference
        :param parser: which lxml.Parser class to use — ``"xml"`` or ``"html"``
        """
        self.maxDiff = 10000
        if original:
            original = _normalize_arch_for_assert(original, parser)
        if expected:
            expected = _normalize_arch_for_assert(expected, parser)
        self.assertEqual(original, expected)

    def assertXMLEqual(self, original: str, expected: str) -> None:
        """Assert two XML arch strings are semantically equal."""
        return self._assertXMLEqual(original, expected)

    def assertHTMLEqual(self, original: str, expected: str) -> None:
        """Assert two HTML arch strings are semantically equal."""
        return self._assertXMLEqual(original, expected, "html")

    def profile(self, description: str = "", **kwargs: Any) -> Any:
        """Return a Profiler for the current test method."""
        test_method = getattr(self, "_testMethodName", "Unknown test method")
        if not hasattr(self, "profile_session"):
            self.profile_session = profiler.make_session(test_method)
        if "db" not in kwargs:
            kwargs["db"] = self.env.cr.dbname
        return profiler.Profiler(
            description="%s uid:%s %s %s"
            % (
                test_method,
                self.env.user.id,
                "warm" if self.warm else "cold",
                description,
            ),
            profile_session=self.profile_session,
            **kwargs,
        )

    @classmethod
    def _registry_test_mode_patches(cls, *, cr: Cursor, registry: Registry):
        """
        Returns the patches required for entering registry test mode.
        The patches are not started.
        """

        def _patched_cursor(readonly: bool = False):
            return TestCursor(
                cr,
                _registry_test_lock,
                readonly and cls._registry_readonly_enabled,
            )

        return [
            # New cursor should point to the test's cursor
            patch.object(registry, "cursor", _patched_cursor),
            # Disable locking and signaling
            patch.object(Registry, "_lock", DummyRLock()),
            patch.object(registry, "setup_signaling", return_value=None),  # noop
            patch.object(registry, "check_signaling", return_value=registry),
        ]

    @classmethod
    def registry_enter_test_mode_cls(cls) -> None:
        """Put the registry in test mode.

        New cursors returned by the registry will be instances of `TestCursor`
        which will wrap the current cursor.
        """
        assert not cls._registry_patched, "Can only patch registry once"
        assert cls.cr, "No cursor"
        assert cls.registry, "No registry"

        cls.registry_patches = cls._registry_test_mode_patches(
            cr=cls.cr,
            registry=cls.registry,
        )
        for p in cls.registry_patches:
            p.start()
        cls._registry_patched = True
        cls.addClassCleanup(cls.registry_leave_test_mode)

    def registry_enter_test_mode(
        self, *, cr: Cursor | None = None, register_cleanup: bool = True
    ) -> None:
        """
        Puts the registry in test mode.

        New cursors returned by the registry will be instances of `TestCursor`
        which will wrap the current cursor.

        :param cr: the cursor to wrap (defaults to the current cursor if none)
        :param register_cleanup: whether to register cleanup.
        """
        assert not type(self)._registry_patched, "Can only patch registry once"
        assert cr or self.cr, "No cursor"
        assert self.registry, "No registry"

        type(self).registry_patches = self._registry_test_mode_patches(
            cr=cr or self.cr,
            registry=self.registry,
        )
        for p in self.registry_patches:
            p.start()
        type(self)._registry_patched = True
        if register_cleanup:
            self.addCleanup(self.registry_leave_test_mode)

    @classmethod
    def registry_leave_test_mode(cls) -> None:
        """Restore the registry to its normal (non-test) mode."""
        assert cls._registry_patched, "Registry is not patched"

        for p in cls.registry_patches:
            p.stop()
        cls.registry_patches.clear()
        cls._registry_patched = False

    @classmethod
    def set_registry_readonly_mode(cls, enabled: bool) -> None:
        """Enable or disable readonly mode for test cursors."""
        assert cls._registry_patched, "Registry is not patched"

        cls._registry_readonly_enabled = enabled

    def assertCanOpenTestCursor(self) -> None:
        """Assert that we can currently open a test cursor."""
        if odoo.modules.module.current_test is not self:
            message = f"Trying to open a test cursor for {self.canonical_tag} while already in a test {odoo.modules.module.current_test.canonical_tag}"
            _logger.runbot(message)
            raise BadRequest(message)
        request = odoo.http.request
        if not request or self.http_request_allow_all:
            return
        http_request_required_key = self.http_request_key
        http_request_key = request.cookies.get(TEST_CURSOR_COOKIE_NAME)
        if http_request_key != http_request_required_key:
            expected = http_request_required_key
            if not expected:
                expected = "None (request are not enabled)"
            _logger.runbot(
                "Request with path %s has been ignored during test as it "
                "does not contain the test_cursor cookie or it is expired."
                ' (required "%s", got "%s")',
                request.httprequest.path,
                expected,
                http_request_key,
            )
            raise BadRequest(
                "Request ignored during test as it does not contain the required cookie."
            )

    def get_method_additional_tags(self, test_method: Callable | None) -> list[str]:
        """Add an ``is_query_count`` tag if the test method uses assertQueryCount."""
        additional_tags = []
        if (
            odoo.tools.config["test_tags"]
            and "is_query_count" in odoo.tools.config["test_tags"]
        ):
            method_source = inspect.getsource(test_method) if test_method else ""
            if "self.assertQueryCount" in method_source:
                additional_tags.append("is_query_count")
        return additional_tags


class Like:
    """
    A string-like object comparable to other strings but where the substring
    '...' can match anything in the other string.

    Example of usage:

        self.assertEqual("SELECT field1, field2, field3 FROM model", Like('SELECT ... FROM model'))
        self.assertIn(Like('Company ... (SF)'), ['TestPartner', 'Company 8 (SF)', 'SomeAdress'])
        self.assertEqual([
            'TestPartner',
            'Company 8 (SF)',
            'Anything else'
        ], [
            'TestPartner',
            Like('Company ... (SF)'),
            Like('...'),
        ])

    In case of mismatch, here is an example of error message

        AssertionError: Lists differ: ['TestPartner', 'Company 8 (LA)', 'Anything else'] != ['TestPartner', ~Company ... (SF), ~...]

        First differing element 1:
        'Company 8 (LA)'
        ~Company ... (SF)~

        - ['TestPartner', 'Company 8 (LA)', 'Anything else']
        + ['TestPartner', ~Company ... (SF), ~...]


    """

    def __init__(self, pattern: str) -> None:
        self.pattern = pattern
        self.regex = ".*".join(
            [re.escape(part.strip()) for part in self.pattern.split("...")]
        )

    # A Like instance is equal to many strings, so it has no usable hash key.
    __hash__ = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, str):
            return NotImplemented
        return bool(re.fullmatch(self.regex, other.strip(), re.DOTALL))

    def __repr__(self) -> str:
        return repr(self.pattern)


class WhitespaceInsensitive(str):
    """A str subclass that compares equal to other strings with equivalent whitespace."""

    __slots__ = ()

    def __hash__(self) -> int:
        return hash(re.sub(r"\s+", " ", self))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, str):
            return NotImplemented
        return re.sub(r"\s+", " ", self) == re.sub(r"\s+", " ", other)


class Approx:  # noqa: PLW1641
    """A wrapper for approximate float comparisons. Uses float_compare under
    the hood.

    Most of the time, :meth:`TestCase.assertAlmostEqual` is more useful, but it
    doesn't work for all helpers.
    """

    def __init__(
        self,
        value: float,
        rounding: int | float | odoo.addons.base.models.res_currency.ResCurrency,
        /,
        decorate: bool,
    ) -> None:
        self.value = value
        self.decorate = decorate
        if isinstance(rounding, int):
            self.cmp = partial(float_compare, precision_digits=rounding)
        elif isinstance(rounding, float):
            self.cmp = partial(float_compare, precision_rounding=rounding)
        else:
            self.cmp = rounding.compare_amounts

    def __repr__(self) -> str:
        if self.decorate:
            return f"~{self.value!r}"
        return repr(self.value)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, (float, int)):
            return NotImplemented
        return self.cmp(self.value, other) == 0


class TransactionCase(BaseCase):
    """Test class in which all test methods are run in a single transaction,
    but each test method is run in a sub-transaction managed by a savepoint.
    The transaction's cursor is always closed without committing.

    The data setup common to all methods should be done in the class method
    `setUpClass`, so that it is done once for all test methods. This is useful
    for test cases containing fast tests but with significant database setup
    common to all cases (complex in-db test data).

    After being run, each test method cleans up the record cache and the
    registry cache. However, there is no cleanup of the registry models and
    fields. If a test modifies the registry (custom models and/or fields), it
    should prepare the necessary cleanup (`self.registry.reset_changes()`).
    """

    muted_registry_logger = mute_logger(odoo.orm.runtime.registry._logger.name)
    freeze_time = None

    @classmethod
    def _gc_filestore(cls) -> None:
        """Garbage-collect the filestore outside of the test cursor."""
        # Attachments created/unlinked during tests accumulate on disk. Crons
        # don't run during tests, so gc manually — and check the filesystem
        # outside the test cursor.
        with Registry(get_db_name()).cursor() as cr:
            gc_env = api.Environment(cr, api.SUPERUSER_ID, {})
            gc_env["ir.attachment"]._gc_file_store_unsafe()

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.addClassCleanup(cls._gc_filestore)
        cls.registry = Registry(get_db_name())
        cls.registry_start_invalidated = cls.registry.registry_invalidated
        cls.registry_start_sequence = cls.registry.registry_sequence
        cls.registry_cache_sequences = dict(cls.registry.cache_sequences)

        def reset_changes():
            if (
                cls.registry_start_sequence != cls.registry.registry_sequence
            ) or cls.registry.registry_invalidated:
                with cls.registry.cursor() as cr:
                    cls.registry._setup_models__(cr)
            cls.registry.registry_invalidated = cls.registry_start_invalidated
            cls.registry.registry_sequence = cls.registry_start_sequence
            with cls.muted_registry_logger:
                cls.registry.clear_all_caches()
            cls.registry.cache_invalidated.clear()
            cls.registry.cache_sequences = cls.registry_cache_sequences

        cls.addClassCleanup(reset_changes)

        def signal_changes():
            if not cls.registry.ready:
                _logger.info("Skipping signal changes during tests")
                return
            if cls.registry.registry_invalidated or cls.registry.cache_invalidated:
                _logger.info("Simulating signal changes during tests")
            if cls.registry.registry_invalidated:
                cls.registry.registry_sequence += 1
            for cache_name in cls.registry.cache_invalidated or ():
                cls.registry.cache_sequences[cache_name] += 1
            cls.registry.registry_invalidated = False
            cls.registry.cache_invalidated.clear()

        cls._signal_changes_patcher = patch.object(
            cls.registry, "signal_changes", signal_changes
        )
        cls.startClassPatcher(cls._signal_changes_patcher)

        cls.cr = cls.registry.cursor()
        cls.addClassCleanup(cast("Cursor", cls.cr).close)

        # Planner-stats floor, class-transaction layer: autovacuum can undo the
        # committed pre-suite floors mid-suite (VACUUM rewrites reltuples=0 for
        # tables whose rows only ever roll back), degrading hot queries back
        # into cartesian nested-loop plans. Re-seed uncommitted: visible to the
        # whole class, rolled back with it, and the stats locks keep autovacuum
        # from resetting the re-seeded tables while the class runs.
        seed_planner_stats(cls.cr)

        def check_cursor_stack():
            for cursor in TestCursor._cursors_stack:
                _logger.info(
                    "One cursor was remaining in the TestCursor stack at the end of the test"
                )
                cursor._closed = True
            TestCursor._cursors_stack = []

        cls.addClassCleanup(check_cursor_stack)

        if cls.freeze_time:
            cls.startClassPatcher(cls.freeze_time)

        def forbidden(*args, **kwars):
            traceback.print_stack()
            raise AssertionError(
                "Cannot commit or rollback a cursor from inside a test, this will lead to a broken cursor when trying to rollback the test. Please rollback to a specific savepoint instead or open another cursor if really necessary"
            )

        cls.commit_patcher = patch.object(cls.cr, "commit", forbidden)
        cls.startClassPatcher(cls.commit_patcher)
        cls.rollback_patcher = patch.object(cls.cr, "rollback", forbidden)
        cls.startClassPatcher(cls.rollback_patcher)
        cls.close_patcher = patch.object(cls.cr, "close", forbidden)
        cls.startClassPatcher(cls.close_patcher)

        cls.env = api.Environment(cls.cr, api.SUPERUSER_ID, {})

        # Speed up CryptContext: tests create many users/passwords; avoid hashing
        # with many rounds.
        def _crypt_context(self):
            return CryptContext(
                ["pbkdf2_sha512", "plaintext"],
                pbkdf2_sha512__rounds=1,
            )

        cls._crypt_context_patcher = patch(
            "odoo.addons.base.models.res_users.ResUsersPatchedInTest._crypt_context",
            _crypt_context,
        )
        cls.startClassPatcher(cls._crypt_context_patcher)

    def setUp(self) -> None:
        super().setUp()

        def _check_registry_lock() -> None:
            if _registry_test_lock.count == 0:
                _logger.warning(
                    "The registry test lock is still released at the end of %s",
                    self.canonical_tag,
                )
            elif _registry_test_lock.count > 1:
                _logger.warning(
                    "The registry test lock was acquired more than once (%s) at the end of %s",
                    _registry_test_lock.count,
                    self.canonical_tag,
                )

        self.addCleanup(_check_registry_lock)
        # restore environments after the test to avoid invoking flush() with an
        # invalid environment (inexistent user id) from another test
        envs = self.env.transaction.envs
        for env in list(envs):
            self.addCleanup(env.clear)
        # restore the set of known environments as it was at setUp
        self.addCleanup(envs.update, list(envs))
        self.addCleanup(envs.clear)

        self.addCleanup(self.muted_registry_logger(self.registry.clear_all_caches))

        # This prevents precommit functions and data from piling up
        # until cr.flush is called in 'assertRaises' clauses
        # (these are not cleared in self.env.clear or envs.clear)
        cr = self.env.cr

        def _reset(cb, funcs, data):
            cb._funcs = funcs
            cb.data = data

        for callback in [
            cr.precommit,
            cr.postcommit,
            cr.prerollback,
            cr.postrollback,
        ]:
            self.addCleanup(
                _reset,
                callback,
                deque(callback._funcs),
                deepcopy(callback.data),
            )

        # flush everything in setUpClass before introducing a savepoint
        self.env.flush_all()

        savepoint = Savepoint(self.cr)
        self.addCleanup(savepoint.close)

    @contextmanager
    def enter_registry_test_mode(self) -> Generator[None]:
        """Make all new cursors opened on this database registry reuse the
        one currently used by the tests. See ``registry_enter_test_mode``.
        """
        # entering the test mode should flush/invalidate all changes in the
        # current environment because changes happen inside other cursors
        env = self.env
        env.flush_all()
        self.registry_enter_test_mode(register_cleanup=False)
        try:
            yield
        finally:
            self.registry_leave_test_mode()
            env.invalidate_all()

    @contextmanager
    def allow_pdf_render(self) -> Generator[None]:
        """Enter registry test mode for PDF rendering if necessary.

        WeasyPrint runs in-process (no subprocess), so no cookie/lock
        workarounds are needed — just ensure the registry is in test mode.
        """
        with ExitStack() as stack:
            if not type(self)._registry_patched:
                stack.enter_context(self.enter_registry_test_mode())
            yield


class SingleTransactionCase(BaseCase):
    """TestCase in which all test methods are run in the same transaction,
    the transaction is started with the first test method and rolled back at
    the end of the last.
    """

    @classmethod
    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if issubclass(cls, TransactionCase):
            _logger.warning(
                "%s inherits from both TransactionCase and SingleTransactionCase",
                cls.__name__,
            )

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.registry = Registry(get_db_name())
        cls.addClassCleanup(cls.registry.reset_changes)
        cls.addClassCleanup(cls.registry.clear_all_caches)

        cls.cr = cls.registry.cursor()
        cls.addClassCleanup(cast("Cursor", cls.cr).close)
        # Same class-transaction planner-stats floor as TransactionCase.
        seed_planner_stats(cls.cr)

        cls.env = api.Environment(cls.cr, api.SUPERUSER_ID, {})

    def setUp(self) -> None:
        super().setUp()
        self.env.flush_all()


def no_retry(arg: Any) -> Any:
    """Disable auto retry on decorated test method or test class."""
    arg._retry = False
    return arg


def users(*logins: str) -> Callable:
    """Decorate a method to execute it once for each given user."""
    assert logins, "Expecting at least one login to execute"

    def users_decorator(func: Callable, /) -> Callable:
        @wraps(func)
        def with_users(self: Any, *args: Any, **kwargs: Any) -> None:
            old_uid = self.uid
            try:
                # retrieve users
                Users = self.env["res.users"].with_context(active_test=False)
                user_id = {
                    user.login: user.id
                    for user in Users.search([("login", "in", list(logins))])
                }
                missing = [login for login in logins if login not in user_id]
                assert not missing, f"No user with login {missing}"
                for login in logins:
                    with self.subTest(login=login):
                        # switch user and execute func
                        self.uid = user_id[login]
                        func(self, *args, **kwargs)
                        self.env.flush_all()
                    # Invalidate the cache between subtests, in order to not reuse
                    # the former user's cache (`test_read_mail`, `test_write_mail`)
                    self.env.invalidate_all()
            finally:
                self.uid = old_uid

        return with_users

    return users_decorator


def warmup(func: Callable, /) -> Callable:
    """Stabilize assertQueries and assertQueryCount assertions.

    Flush pending changes and invalidate the cache, then warm up the ORM caches
    by running the decorated function an extra time before the real run. The extra
    execution ignores assertQueries/assertQueryCount assertions and discards all
    changes except ORM cache ones.
    """

    @wraps(func)
    def warmup(self: Any, *args: Any, **kwargs: Any) -> None:
        self.env.flush_all()
        self.env.invalidate_all()
        # run once to warm up the caches
        self.warm = False
        with contextlib.closing(self.cr.savepoint(flush=False)):
            func(self, *args, **kwargs)
            self.env.flush_all()
        # run once for real
        self.env.invalidate_all()
        self.warm = True
        func(self, *args, **kwargs)

    return warmup


def can_import(module: str) -> bool:
    """Check if ``module`` can be imported.

    Returns ``True`` if it can be, ``False`` otherwise.  Use with
    ``unittest.skipUnless`` for tests conditional on optional dependencies.
    """
    try:
        importlib.import_module(module)
    except ImportError:
        return False
    else:
        return True


def tagged(*tags: str) -> Callable:
    """Decorate a BaseCase class to add or remove test tags.

    Tags are stored in a set accessible via the ``test_tags`` attribute.
    A tag prefixed by ``'-'`` removes that tag (e.g. ``'-standard'``).

    By default, all test classes from ``odoo.tests.common`` have
    ``test_tags`` defaulting to ``{'standard', 'at_install'}``.
    Tags are inherited through class inheritance.
    """
    include = {t for t in tags if not t.startswith("-")}
    exclude = {t[1:] for t in tags if t.startswith("-")}

    def tags_decorator(obj: Any) -> Any:
        obj.test_tags = (getattr(obj, "test_tags", set()) | include) - exclude
        at_install = "at_install" in obj.test_tags
        post_install = "post_install" in obj.test_tags
        if not (at_install ^ post_install):
            _logger.warning(
                "A tests should be either at_install or post_install, which is not the case of %r",
                obj,
            )
        return obj

    return tags_decorator


class freeze_time:
    """Odoo-aware replacement for freezegun in test suites.

    Properly handles test class decoration and can also be used as a
    method decorator or context manager.
    """

    _freeze_time = staticmethod(freezegun.freeze_time)

    def __init__(
        self,
        time_to_freeze: Any = None,
        tz_offset: int = 0,
        tick: bool = False,
        as_kwarg: str = "",
        auto_tick_seconds: int = 0,
    ) -> None:
        self.freezer = self._freeze_time(
            time_to_freeze=time_to_freeze,
            tz_offset=tz_offset,
            tick=tick,
            as_kwarg=as_kwarg,
            auto_tick_seconds=auto_tick_seconds,
        )

    def __call__(self, arg: Any) -> Any:
        """Apply freeze_time as a class or method decorator."""
        if isinstance(arg, type) and issubclass(arg, case.TestCase):
            arg.freeze_time = self
            return arg

        return self.freezer(arg)

    def __enter__(self) -> Any:
        return self.freezer.start()

    def __exit__(self, *args: Any) -> None:
        self.freezer.stop()

    start = __enter__
    stop = __exit__


# Replace freezegun's entry point process-wide: hundreds of test files
# import freezegun directly and rely on getting the Odoo-aware wrapper above
# (class decoration via cls.freeze_time + TransactionCase integration).
# Server processes only import odoo.tests lazily in test mode, so in
# practice the patch stays test-scoped.
freezegun.freeze_time = freeze_time

# HTTP layer — extracted to http.py (like the Chrome CDP client before it,
# see browser.py); re-imported here so odoo.tests.common.HttpCase & co.
# remain valid import and mock targets.
from .http import HttpCase, JsonRpcException, Opener, Transport  # noqa: E402
