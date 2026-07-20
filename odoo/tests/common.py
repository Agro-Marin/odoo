"""
The module :mod:`odoo.tests.common` provides unittest test cases and a few
helpers and classes to write tests.

"""

import base64
import binascii
import concurrent.futures
import contextlib
import difflib
import gc
import importlib
import inspect
import itertools
import json
import logging
import os
import pathlib
import platform
import pprint
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
import warnings
from collections import defaultdict, deque
from concurrent.futures import CancelledError, Future, InvalidStateError, wait
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import datetime
from functools import lru_cache, partial, wraps
from itertools import islice, zip_longest
from textwrap import shorten
from typing import TYPE_CHECKING, Any, cast
from unittest import TestResult
from unittest.mock import Mock, _patch, patch
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from uuid import uuid4
from xmlrpc import client as xmlrpclib

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
from odoo.service import security
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
from odoo.tools.misc import find_in_path, lower_logging
from odoo.tools.password import CryptContext
from odoo.tools.xml_utils import _validate_xml

import odoo.addons.base
from . import case, test_cursor

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable

    from .result import OdooTestResult

try:
    import websocket
except ImportError:
    # chrome headless tests will be skipped
    websocket = None

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


# The odoo library is supposed already configured.
HOST = "127.0.0.1"
# Useless constant, tests are aware of the content of demo data
ADMIN_USER_ID = api.SUPERUSER_ID

CHECK_BROWSER_SLEEP = 0.1  # seconds
CHECK_BROWSER_ITERATIONS = 100
BROWSER_WAIT = CHECK_BROWSER_SLEEP * CHECK_BROWSER_ITERATIONS  # seconds
DEFAULT_SUCCESS_SIGNAL = "test successful"
TEST_CURSOR_COOKIE_NAME = "test_request_key"

IGNORED_MSGS = re.compile(
    r"""
    failed\ to\ fetch  # base error
  | connectionlosterror:  # conversion by offlineFailToFetchErrorHandler
  | assetsloadingerror:  # lazy loaded bundle
""",
    flags=re.VERBOSE | re.IGNORECASE,
).search


def get_db_name() -> str:
    """Return the configured test database name."""
    dbnames = odoo.tools.config["db_name"]
    # If the database name is not provided on the command-line,
    # use the one on the thread (which means if it is provided on
    # the command-line, this will break when installing another
    # database from XML-RPC).
    if not dbnames and hasattr(threading.current_thread(), "dbname"):
        return threading.current_thread().dbname
    if len(dbnames) > 1:
        sys.exit(
            "-d/--database/db_name has multiple database, please provide a single one"
        )
    return dbnames[0]


standalone_tests = defaultdict(list)


class RegistryRLock(threading._RLock):
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
            exit(f"Could not re-acquire the registry lock during {tag}, exiting...")


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
    def decorator(func):
        def wrapped_f(self, *args, **kwargs):
            if not skip:
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
    Parser = None
    if parser_method == "xml":
        Parser = etree.XMLParser
    elif parser_method == "html":
        Parser = etree.HTMLParser
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
        cases not having them. Also sets a completely unnecessary
        ``test_module`` attribute.
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

    _tests_run_count = int(os.environ.get("ODOO_TEST_FAILURE_RETRIES", "0")) + 1

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
            # switch user
            self.uid = user.id
            self.env = self.env(user=self.uid)
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
            return test_cursor.TestCursor(
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
                "it does not contain the test_cursor cookie or it is expired."
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

    def __eq__(self, other: object) -> bool | NotImplemented:
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
            for cursor in test_cursor.TestCursor._cursors_stack:
                _logger.info(
                    "One cursor was remaining in the TestCursor stack at the end of the test"
                )
                cursor._closed = True
            test_cursor.TestCursor._cursors_stack = []

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
                "%s inherits from both TransactionCase and SingleTransactionCase"
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


class ChromeBrowserException(Exception):
    pass


def run(gen_func):
    def done(f):
        try:
            try:
                r = f.result()
            except Exception as e:
                f = coro.throw(e)
            else:
                f = coro.send(r)
        except StopIteration:
            return

        assert isinstance(f, Future), f"coroutine must yield futures, got {f}"
        f.add_done_callback(done)

    coro = gen_func()
    try:
        next(coro).add_done_callback(done)
    except StopIteration:
        return


def save_test_file(
    test_name: str,
    content: bytes,
    prefix: str,
    extension: str = "png",
    logger: logging.Logger = _logger,
    document_type: str = "Screenshot",
    date_format: str = "%Y%m%d_%H%M%S_%f",
) -> None:
    """Save a test artifact (screenshot, screencast frame, etc.) to disk."""
    assert re.fullmatch(r"\w*_", prefix)
    assert re.fullmatch(r"[a-z]+", extension)
    assert re.fullmatch(r"\w+", test_name)
    now = datetime.now().strftime(date_format)
    screenshots_dir = (
        pathlib.Path(odoo.tools.config["screenshots"]) / get_db_name() / "screenshots"
    )
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    full_path = screenshots_dir / f"{prefix}{now}_{test_name}.{extension}"
    full_path.write_bytes(content)
    logger.runbot(f"{document_type} in: {full_path}")


if os.name == "posix" and platform.system() != "Darwin":
    import resource

    # since the introduction of pointer compression in Chrome 80 (v8 v8.0),
    # the memory reservation algorithm requires more than 8GiB of
    # virtual mem for alignment this exceeds our default memory limits.
    def _preexec():
        resource.setrlimit(
            resource.RLIMIT_AS, (resource.RLIM_INFINITY, resource.RLIM_INFINITY)
        )

else:
    _preexec = None


class ChromeBrowser:
    """Helper object to control a Chrome headless process."""

    remote_debugging_port = 0  # 9222, change it in a non-git-tracked file

    def __init__(
        self,
        test_case: HttpCase,
        success_signal: str = DEFAULT_SUCCESS_SIGNAL,
        headless: bool = True,
        debug: bool = False,
    ):
        self.throttling_factor = 1
        self._logger = test_case._logger
        self.test_case = test_case
        self.success_signal = success_signal
        if websocket is None:
            self._logger.warning("websocket-client module is not installed")
            raise unittest.SkipTest("websocket-client module is not installed")
        self.user_data_dir = tempfile.mkdtemp(suffix="_chrome_odoo")

        if scs := odoo.tools.config["screencasts"]:
            self.screencaster = Screencaster(self, scs)
        else:
            self.screencaster = NoScreencast()

        if os.name == "posix":
            self.sigxcpu_handler = signal.getsignal(signal.SIGXCPU)
            signal.signal(signal.SIGXCPU, self.signal_handler)
        else:
            self.sigxcpu_handler = None

        test_case.browser_size = test_case.browser_size.replace("x", ",")

        self.chrome, self.devtools_port = self._chrome_start(
            user_data_dir=self.user_data_dir,
            touch_enabled=test_case.touch_enabled,
            headless=headless,
            debug=debug,
        )
        self.ws = self._open_websocket()
        self._request_id = itertools.count()
        self._result = Future()
        self.error_checker = None
        self.had_failure = False
        # maps request_id to Futures
        self._responses = {}
        # maps frame ids to callbacks
        self._frames = {}
        self._handlers = {
            "Fetch.requestPaused": self._handle_request_paused,
            "Runtime.consoleAPICalled": self._handle_console,
            "Runtime.exceptionThrown": self._handle_exception,
            "Page.frameStoppedLoading": self._handle_frame_stopped_loading,
            "Page.screencastFrame": self.screencaster,
        }
        # Python 3.14 intermittently refuses pthread_create under test-suite load,
        # so Thread.start() can raise RuntimeError; the refusal clears within a few
        # hundred ms. Retry after gc + a short sleep, with a fresh Thread each time
        # (Thread.start() only accepts one call per instance).
        for attempt in range(5):
            self._receiver = threading.Thread(
                target=self._receive,
                name="WebSocket events consumer",
                args=(get_db_name(),),
                daemon=True,
            )
            try:
                self._receiver.start()
                break
            except RuntimeError:
                gc.collect()
                time.sleep(0.2 * (attempt + 1))
        else:
            self._receiver.start()  # surface the original error
        self._logger.info("Enable chrome headless console log notification")
        self._websocket_send("Runtime.enable")
        self._websocket_request("Fetch.enable")
        self._logger.info("Chrome headless enable page notifications")
        self._websocket_send("Page.enable")
        self._websocket_send(
            "Page.setDownloadBehavior",
            params={
                "behavior": "deny",
                "eventsEnabled": False,
            },
        )
        self._websocket_send(
            "Emulation.setFocusEmulationEnabled", params={"enabled": True}
        )
        emulated_device = {
            "mobile": False,
            "width": None,
            "height": None,
            "deviceScaleFactor": 1,
        }
        emulated_device["width"], emulated_device["height"] = [
            int(size) for size in test_case.browser_size.split(",")
        ]
        self._websocket_request(
            "Emulation.setDeviceMetricsOverride", params=emulated_device
        )

    def signal_handler(self, sig: int, frame: Any) -> None:
        """Handle SIGXCPU by stopping Chrome and exiting."""
        if sig == signal.SIGXCPU:
            _logger.info("CPU time limit reached, stopping Chrome and shutting down")
            self.stop()
            exit()

    def throttle(self, factor: int | None) -> None:
        if not factor:
            return

        assert 1 <= factor <= 50  # arbitrary upper limit
        self.throttling_factor = factor
        self._websocket_request(
            "Emulation.setCPUThrottlingRate", params={"rate": factor}
        )

    def stop(self) -> None:
        """Stop the Chrome browser process and clean up resources."""
        # method may be called during `_open_websocket`
        if hasattr(self, "ws"):
            try:
                self.screencaster.stop()

                self._websocket_request("Page.stopLoading")
                self._websocket_request(
                    "Runtime.evaluate",
                    params={
                        "expression": """
                ('serviceWorker' in navigator) &&
                    navigator.serviceWorker.getRegistrations().then(
                        registrations => Promise.all(registrations.map(r => r.unregister()))
                    )
                """,
                        "awaitPromise": True,
                    },
                )
                # wait for any in-flight responses (e.g. the screenshot)
                wait(self._responses.values(), 10)
                self._result.cancel()

                self._logger.info(
                    "Closing chrome headless with pid %s", self.chrome.pid
                )
                self._websocket_request("Browser.close")
            except ChromeBrowserException as e:
                _logger.runbot("WS error during browser shutdown: %s", e)
            except Exception:
                _logger.warning("Error during browser shutdown", exc_info=True)
            self._logger.info("Closing websocket connection")
            self.ws.close()

        self._logger.info("Terminating chrome headless with pid %s", self.chrome.pid)
        # terminating the main process doesn't reap its children; collect the
        # whole tree first, then SIGKILL whatever survives. NoSuchProcess: stop()
        # may run after Chrome already exited.
        try:
            main = psutil.Process(self.chrome.pid)
            procs = [main, *main.children(recursive=True)]
        except psutil.NoSuchProcess:
            procs = []
        self.chrome.terminate()
        _, alive = psutil.wait_procs(procs, 5)
        if alive:
            self._logger.warning(
                "Killing chrome descendants-or-self of %s: %d remaining%s",
                self.chrome.pid,
                len(alive),
                "".join(f"\n- {p.name()} ({p.status()})" for p in alive),
            )
            for p in alive:
                p.kill()
            psutil.wait_procs(alive, 1)

        self._logger.info('Removing chrome user profile "%s"', self.user_data_dir)
        shutil.rmtree(self.user_data_dir, ignore_errors=True)

        # Restore previous signal handler
        if self.sigxcpu_handler:
            signal.signal(signal.SIGXCPU, self.sigxcpu_handler)

    @property
    def executable(self):
        try:
            return _find_executable()
        except Exception:
            self._logger.warning("Chrome executable not found")
            raise

    def _spawn_chrome(self, cmd: list[str]) -> tuple[subprocess.Popen, int]:
        """Spawn a Chrome subprocess and wait for it to expose the DevTools port."""
        log_path = pathlib.Path(self.user_data_dir, "err.log")
        with log_path.open("wb") as log_file:
            # pylint: disable=subprocess-popen-preexec-fn
            # TMPDIR -> profile dir so Chrome's `org.chromium.*` scratch dirs get
            # removed with the profile instead of littering the system temp dir.
            proc = subprocess.Popen(
                cmd,
                stderr=log_file,
                preexec_fn=_preexec,  # noqa: PLW1509
                env={**os.environ, "TMPDIR": self.user_data_dir},
            )

        port_file = pathlib.Path(self.user_data_dir, "DevToolsActivePort")
        for _ in range(CHECK_BROWSER_ITERATIONS):
            time.sleep(CHECK_BROWSER_SLEEP)
            if port_file.is_file() and port_file.stat().st_size > 5:
                with port_file.open("r", encoding="utf-8") as f:
                    return proc, int(f.readline())

        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        self._logger.warning(
            "Chrome headless failed to start:\n%s",
            log_path.read_text(encoding="utf-8"),
        )
        # Chrome never started, so stop() won't run — clean up the profile dir here.
        shutil.rmtree(self.user_data_dir, ignore_errors=True)

        raise unittest.SkipTest(
            f"Failed to detect chrome devtools port after {BROWSER_WAIT:.1f}s."
        )

    def _chrome_start(
        self,
        user_data_dir: str,
        touch_enabled: bool,
        headless: bool = True,
        debug: bool | str = False,
    ) -> tuple[subprocess.Popen, int]:
        headless_switches = {
            "--headless": "",
            "--disable-extensions": "",
            "--disable-background-networking": "",
            "--disable-background-timer-throttling": "",
            "--disable-backgrounding-occluded-windows": "",
            "--disable-renderer-backgrounding": "",
            "--disable-breakpad": "",
            "--disable-client-side-phishing-detection": "",
            "--disable-crash-reporter": "",
            "--disable-dev-shm-usage": "",
            "--disable-namespace-sandbox": "",
            "--disable-translate": "",
            "--no-sandbox": "",
            "--disable-gpu": "",
            "--enable-unsafe-swiftshader": "",
            "--mute-audio": "",
        }
        switches = {
            # required for tours that use Youtube autoplay conditions (namely website_slides' "course_tour")
            "--autoplay-policy": "no-user-gesture-required",
            "--disable-default-apps": "",
            "--disable-device-discovery-notifications": "",
            "--no-default-browser-check": "",
            "--remote-debugging-address": HOST,
            "--remote-debugging-port": str(self.remote_debugging_port),
            "--user-data-dir": user_data_dir,
            "--no-first-run": "",
            # FIXME: these next 2 flags are temporarily uncommented to allow client
            # code to manually run garbage collection. This is done as currently
            # the Chrome unit test process doesn't have access to its available
            # memory, so it cannot run the GC efficiently and may run out of memory
            # and crash. These should be re-commented when the process is correctly
            # configured.
            "--enable-precise-memory-info": "",
            "--js-flags": "--expose-gc",
        }
        if headless:
            switches.update(headless_switches)
        if touch_enabled:
            # enable Chrome's Touch mode, useful to detect touch capabilities using
            # "'ontouchstart' in window"
            switches["--touch-events"] = ""
        if debug is not False:
            switches["--auto-open-devtools-for-tabs"] = ""
            switches["--start-fullscreen"] = ""

        cmd = [self.executable]
        cmd += ["%s=%s" % (k, v) if v else k for k, v in switches.items()]
        url = "about:blank"
        cmd.append(url)
        try:
            proc, devtools_port = self._spawn_chrome(cmd)
        except OSError:
            raise unittest.SkipTest("%s not found" % cmd[0]) from None
        self._logger.info("Chrome pid: %s", proc.pid)
        self._logger.info(
            "Chrome headless temporary user profile dir: %s", self.user_data_dir
        )

        return proc, devtools_port

    def _json_command(self, command: str, timeout: int = 3) -> Any:
        """Queries browser state using JSON

        Available commands:

        ``''``
            return list of tabs with their id
        ``list`` (or ``json/``)
            list tabs
        ``new``
            open a new tab
        :samp:`activate/{id}`
            activate a tab
        :samp:`close/{id}`
            close a tab
        ``version``
            get chrome and dev tools version
        ``protocol``
            get the full protocol
        """
        url = f"http://{HOST}:{self.devtools_port}/json/{command}".rstrip("/")
        self._logger.info("Issuing json command %s", url)
        delay = 0.1
        tries = 0
        failure_info = None
        message = None
        while timeout > 0:
            if self.chrome.poll() is not None:
                message = "Chrome crashed at startup"
                break
            try:
                r = requests.get(url, timeout=3)
                if r.ok:
                    return r.json()
            except requests.ConnectionError as e:
                failure_info = str(e)
                message = "Connection Error while trying to connect to Chrome debugger"
            except requests.exceptions.ReadTimeout as e:
                failure_info = str(e)
                message = (
                    "Connection Timeout while trying to connect to Chrome debugger"
                )
                break

            time.sleep(delay)
            timeout -= delay
            delay = delay * 1.5
            tries += 1
        self._logger.error("%s after %s tries", message, tries)
        if failure_info:
            self._logger.info(failure_info)
        self.stop()
        raise unittest.SkipTest("Error during Chrome headless connection")

    def _open_websocket(self) -> Any:
        """Connect to Chrome's DevTools WebSocket endpoint."""
        version = self._json_command("version")
        self._logger.info("Browser version: %s", version["Browser"])

        start = time.time()
        while (time.time() - start) < 5.0:
            ws_url = next(
                (
                    target["webSocketDebuggerUrl"]
                    for target in self._json_command("")
                    if target["type"] == "page"
                    if target["url"] == "about:blank"
                ),
                None,
            )
            if ws_url:
                break

            time.sleep(0.1)
        else:
            self.stop()
            raise unittest.SkipTest(
                "Error during Chrome connection: never found 'page' target"
            )

        self._logger.info("Websocket url found: %s", ws_url)
        ws = websocket.create_connection(
            ws_url, enable_multithread=True, suppress_origin=True
        )
        if ws.getstatus() != 101:
            raise unittest.SkipTest("Cannot connect to chrome dev tools")
        ws.settimeout(0.01)
        return ws

    def _receive(self, dbname: str) -> None:
        """Receive and dispatch WebSocket messages from Chrome DevTools."""
        threading.current_thread().dbname = dbname
        # So CDT uses a streamed JSON-RPC structure, meaning a request is
        # {id, method, params} and eventually a {id, result | error} should
        # arrive the other way, however for events it uses "notifications"
        # meaning request objects without an ``id``, but *coming from the server
        while True:  # or maybe until `self._result` is `done()`?
            try:
                msg = self.ws.recv()
                if not msg:
                    continue
                self._logger.debug("\n<- %s", msg)
            except websocket.WebSocketTimeoutException:
                continue
            except websocket.WebSocketConnectionClosedException as e:
                if not self._result.done():
                    del self.ws
                    self._result.set_exception(e)
                    # drain destructively: cancelling a future can mutate
                    # `_responses` mid-iteration
                    while True:
                        try:
                            _, f = self._responses.popitem()
                        except KeyError:
                            break
                        else:
                            f.cancel()
                return
            except Exception as e:
                if isinstance(e, ConnectionResetError) and self._result.done():
                    return
                # if the socket is still connected something bad happened,
                # otherwise the client was just shut down
                if self.ws.connected:
                    self._result.set_exception(e)
                    raise
                self._result.cancel()
                return

            res = json.loads(msg)
            request_id = res.get("id")
            try:
                if request_id is None:
                    if handler := self._handlers.get(res["method"]):
                        handler(**res["params"])
                elif f := self._responses.pop(request_id, None):
                    if "result" in res:
                        f.set_result(res["result"])
                    else:
                        f.set_exception(ChromeBrowserException(res["error"]["message"]))
            except Exception:
                _logger.exception(
                    "While processing message %s",
                    shorten(str(msg), 500, placeholder="..."),
                )

    def _websocket_request(
        self, method: str, *, params: dict | None = None, timeout: float = 10.0
    ) -> Any:
        assert threading.get_ident() != self._receiver.ident, (
            "_websocket_request must not be called from the consumer thread"
        )
        if not hasattr(self, "ws"):
            return None

        f = self._websocket_send(method, params=params, with_future=True)
        try:
            return f.result(timeout=timeout * self.throttling_factor)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"{method}({params or ''})") from None

    def _websocket_send(
        self, method: str, *, params: dict | None = None, with_future: bool = False
    ) -> Future | None:
        """Send Chrome DevTools Protocol commands through the WebSocket.

        If ``with_future`` is set, returns a ``Future`` for the operation.
        """
        if not hasattr(self, "ws"):
            return None

        result = None
        request_id = next(self._request_id)
        if with_future:
            result = self._responses[request_id] = Future()
        payload = {"method": method, "id": request_id}
        if params:
            payload["params"] = params
        self._logger.debug("\n-> %s", payload)
        self.ws.send(json.dumps(payload))
        return result

    def _handle_request_paused(self, **params: Any) -> None:
        """Handle a Fetch.requestPaused event by continuing or blocking the request."""
        url = params["request"]["url"]
        if url.startswith(f"http://{HOST}"):
            cmd = "Fetch.continueRequest"
            response = {}
        else:
            cmd = "Fetch.fulfillRequest"
            response = self.test_case.fetch_proxy(url)
        try:
            self._websocket_send(
                cmd, params={"requestId": params["requestId"], **response}
            )
        except websocket.WebSocketConnectionClosedException:
            pass
        except BrokenPipeError, ConnectionResetError, OSError:
            # this can happen if the browser is closed. Just ignore it.
            _logger.info(
                "Websocket error while handling request %s",
                params["request"]["url"],
            )

    def _handle_console(
        self,
        type: str,
        args: list | None = None,
        stackTrace: dict | None = None,
        **kw: Any,
    ) -> None:  # pylint: disable=redefined-builtin
        # console formatting differs somewhat from Python's, if args[0] has
        # format modifiers that many of args[1:] get formatted in, missing
        # args are replaced by empty strings and extra args are concatenated
        # (space-separated)
        #
        # current version modifies the args in place which could and should
        # probably be improved
        if args:
            arg0, args = str(self._from_remoteobject(args[0])), args[1:]
        else:
            arg0, args = "", []
        formatted = [re.sub(r"%[%sdfoOc]", self.console_formatter(args), arg0)]
        # formatter consumes args it uses, leaves unformatted args untouched
        formatted.extend(str(self._from_remoteobject(arg)) for arg in args)
        message = " ".join(formatted)
        stack = "".join(self._format_stack({"type": type, "stackTrace": stackTrace}))
        if stack:
            message += "\n" + stack

        log_type = type
        _logger = self._logger.getChild("browser")
        if self._result.done() and IGNORED_MSGS(message):
            log_type = "dir"
        _logger.log(
            self._TO_LEVEL.get(log_type, logging.INFO),
            "%s%s",
            "Error received after termination: " if self._result.done() else "",
            message,  # might still have %<x> characters
        )

        if log_type == "error":
            self.had_failure = True
            if self._result.done():
                return
            if not self.error_checker or self.error_checker(message):
                self.take_screenshot()
                try:
                    self._result.set_exception(ChromeBrowserException(message))
                except CancelledError:
                    ...
                except InvalidStateError:
                    self._logger.warning(
                        "Trying to set result to failed (%s) but found the future settled (%s)",
                        message,
                        self._result,
                    )
        elif message == self.success_signal:

            @run
            def _get_heap():
                yield self._websocket_send(
                    "HeapProfiler.collectGarbage", with_future=True
                )
                r = yield self._websocket_send("Runtime.getHeapUsage", with_future=True)
                _logger.info("heap %d (allocated %d)", r["usedSize"], r["totalSize"])

            @run
            def _check_form():
                node_id = 0

                with contextlib.suppress(Exception):
                    d = yield self._websocket_send(
                        "DOM.getDocument", params={"depth": 0}, with_future=True
                    )
                    form = yield self._websocket_send(
                        "DOM.querySelector",
                        params={
                            "nodeId": d["root"]["nodeId"],
                            "selector": ".o_form_dirty",
                        },
                        with_future=True,
                    )
                    node_id = form["nodeId"]

                if node_id:
                    self.take_screenshot("unsaved_form_")
                    msg = """\
Tour finished with a dirty form view being open.

Dirty form views are automatically saved when the page is closed, \
which leads to stray network requests and inconsistencies."""
                    if self._result.done():
                        _logger.error("%s", msg)
                    else:
                        self._result.set_exception(ChromeBrowserException(msg))
                    return

                if not self._result.done():
                    self._result.set_result(True)
                elif self._result.exception() is None:
                    _logger.error("Tried to make the tour successful twice.")

    def _handle_exception(self, exceptionDetails: dict, timestamp: float) -> None:
        """Handle a Runtime.exceptionThrown event."""
        message = exceptionDetails["text"]
        exception = exceptionDetails.get("exception")
        if exception:
            message += str(self._from_remoteobject(exception))
        exceptionDetails["type"] = "trace"  # fake this so _format_stack works
        stack = "".join(self._format_stack(exceptionDetails))
        if stack:
            message += "\n" + stack

        if self._result.done():
            if not IGNORED_MSGS(message):
                self._logger.getChild("browser").error(
                    "Exception received after termination: %s", message
                )
            return

        self.take_screenshot()
        try:
            self._result.set_exception(ChromeBrowserException(message))
        except CancelledError:
            ...
        except InvalidStateError:
            self._logger.warning(
                "Trying to set result to failed (%s) but found the future settled (%s)",
                message,
                self._result,
            )

    def _handle_frame_stopped_loading(self, frameId: str) -> None:
        """Handle a Page.frameStoppedLoading event."""
        wait = self._frames.pop(frameId, None)
        if wait:
            wait()

    _TO_LEVEL = {
        "debug": logging.DEBUG,
        "log": logging.INFO,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "dir": logging.RUNBOT,
        # TODO: what do with
        # dir, dirxml, table, trace, clear, startGroup, startGroupCollapsed,
        # endGroup, assert, profile, profileEnd, count, timeEnd
    }

    def take_screenshot(self, prefix="sc_") -> Future[dict]:
        def handler(f):
            try:
                base_png = f.result(timeout=0)["data"]
            except Exception as e:
                self._logger.runbot("Couldn't capture screenshot: %s", e)
                return
            if not base_png:
                self._logger.runbot(
                    "Couldn't capture screenshot: expected image data, got %r",
                    base_png,
                )
                return
            decoded = binascii.a2b_base64(base_png)
            save_test_file(
                type(self.test_case).__name__,
                decoded,
                prefix,
                logger=self._logger,
            )

        self._logger.info("Asking for screenshot")
        f = self._websocket_send("Page.captureScreenshot", with_future=True)
        if f:
            f.add_done_callback(handler)
        return f

    def set_cookie(
        self,
        name: str,
        value: str,
        path: str,
        domain: str,
        *,
        http_only: bool = False,
    ) -> None:
        """Set a cookie in the Chrome browser via DevTools.

        :param http_only: when True, the cookie is hidden from
            ``document.cookie`` reads (HTML spec). Use this for cookies
            that exist purely for server-side correlation and would
            otherwise leak into JS-visible state — notably the
            ``test_request_key`` cookie used by the test-cursor lock.
        """
        params = {"name": name, "value": value, "path": path, "domain": domain}
        if http_only:
            params["httpOnly"] = True
        self._websocket_request("Network.setCookie", params=params)

    def delete_cookie(self, name: str, **kwargs: str) -> None:
        """Delete a cookie in the Chrome browser via DevTools."""
        params = {k: v for k, v in kwargs.items() if k in ["url", "domain", "path"]}
        params["name"] = name
        self._websocket_request("Network.deleteCookies", params=params)

    def _wait_ready(self, ready_code: str | None = None, timeout: int = 60) -> bool:
        timeout *= self.throttling_factor
        ready_code = ready_code or "document.readyState === 'complete'"
        self._logger.info('Evaluate ready code "%s"', ready_code)
        start_time = time.time()
        result = None
        while True:
            taken = time.time() - start_time
            if taken > timeout:
                break

            try:
                result = self._websocket_request(
                    "Runtime.evaluate",
                    params={
                        "expression": "try { %s } catch {}" % ready_code,
                        "awaitPromise": True,
                    },
                    timeout=timeout - taken,
                )["result"]
            except CancelledError:
                # surface the real cause stored on `_result` (e.g. WS closed)
                # instead of a bare CancelledError; otherwise retry until timeout
                exc = self._result.done() and self._result.exception()
                if exc:
                    raise exc from None
                result = "cancelled"

            if result == {"type": "boolean", "value": True}:
                time_to_ready = time.time() - start_time
                if taken > 2:
                    self._logger.info(
                        "The ready code tooks too much time : %s", time_to_ready
                    )
                return True

        exc = self._result.done() and self._result.exception()
        if exc:
            raise exc from None
        self.take_screenshot(prefix="sc_failed_ready_")
        self._logger.info("Ready code last try result: %s", result)
        return False

    def _wait_code_ok(
        self, code: str, timeout: float, error_checker: Callable | None = None
    ) -> None:
        timeout *= self.throttling_factor
        self.error_checker = error_checker
        self._logger.info('Evaluate test code "%s"', code)
        start = time.time()
        res = self._websocket_request(
            "Runtime.evaluate",
            params={
                "expression": code,
                "awaitPromise": True,
            },
            timeout=timeout,
        )["result"]
        if res.get("subtype") == "error":
            raise ChromeBrowserException("Running code returned an error: %s" % res)

        err = ChromeBrowserException("failed")
        try:
            # if the runcode was a promise which took some time to execute,
            # discount that from the timeout
            if (
                self._result.result(time.time() - start + timeout)
                and not self.had_failure
            ):
                return
        except CancelledError:
            # regular-ish shutdown
            return
        except ChromeBrowserException:
            self.screencaster.save()
            raise
        except Exception as e:
            err = e

        self.take_screenshot()
        self.screencaster.save()

        if isinstance(err, concurrent.futures.TimeoutError):
            raise ChromeBrowserException("Script timeout exceeded") from err
        raise ChromeBrowserException("Unknown error") from err

    def navigate_to(self, url: str, wait_stop: bool = False) -> None:
        """Navigate the browser to the given URL."""
        self._logger.info('Navigating to: "%s"', url)
        nav_result = self._websocket_request(
            "Page.navigate", params={"url": url}, timeout=20.0
        )
        self._logger.info("Navigation result: %s", nav_result)
        if wait_stop:
            frame_id = nav_result["frameId"]
            e = threading.Event()
            self._frames[frame_id] = e.set
            self._logger.info("Waiting for frame %r to stop loading", frame_id)
            e.wait(10)

    def _from_remoteobject(self, arg: dict) -> Any:
        """Attempt to make a CDT RemoteObject comprehensible."""
        objtype = arg["type"]
        subtype = arg.get("subtype")
        if objtype == "undefined":
            # the undefined remoteobject is literally just {type: undefined}...
            return "undefined"
        elif objtype != "object" or subtype not in (None, "array"):
            # value is the json representation for json object
            # otherwise fallback on the description which is "a string
            # representation of the object" e.g. the traceback for errors, the
            # source for functions, ... finally fallback on the entire arg mess
            return arg.get("value", arg.get("description", arg))
        elif subtype == "array":
            # apparently value is *not* the JSON representation for arrays
            # instead it's just Array(3) which is useless, however the preview
            # properties are the same as object which is useful (just ignore the
            # name which is the index)
            return "[%s]" % ", ".join(
                repr(p["value"]) if p["type"] == "string" else str(p["value"])
                for p in arg.get("preview", {}).get("properties", [])
                if re.match(r"\d+", p["name"])
            )
        # all that's left is type=object, subtype=None aka custom or
        # non-standard objects, print as TypeName(param=val, ...), sadly because
        # of the way Odoo widgets are created they all appear as Class(...)
        # nb: preview properties are *not* recursive, the value is *all* we get
        return "%s(%s)" % (
            arg.get("className") or "object",
            ", ".join(
                "%s=%s"
                % (
                    p["name"],
                    repr(p["value"]) if p["type"] == "string" else p["value"],
                )
                for p in arg.get("preview", {}).get("properties", [])
                if p.get("value") is not None
            ),
        )

    LINE_PATTERN = "\tat %(functionName)s (%(url)s:%(lineNumber)d:%(columnNumber)d)\n"

    def _format_stack(self, logrecord: dict) -> Generator[str]:
        """Yield formatted stack frame lines from a CDT log record."""
        if logrecord["type"] != "trace":
            return

        trace = logrecord.get("stackTrace")
        while trace:
            for f in trace["callFrames"]:
                yield self.LINE_PATTERN % f
            trace = trace.get("parent")

    def console_formatter(self, args: list) -> Callable:
        """Formats similarly to the console API:

        * if there are no args, don't format (return string as-is)
        * %% -> %
        * %c -> replace by styling directives (ignore for us)
        * other known formatters -> replace by corresponding argument
        * leftover known formatters (args exhausted) -> replace by empty string
        * unknown formatters -> return as-is
        """
        if not args:
            return lambda m: m[0]

        def replacer(m):
            fmt = m[0][1]
            if fmt == "%":
                return "%"
            if fmt in "sdfoOc":
                if not args:
                    return ""
                repl = args.pop(0)
                if fmt == "c":
                    return ""
                return str(self._from_remoteobject(repl))
            return m[0]

        return replacer


class NoScreencast:
    """No-op screencast implementation used when screencasting is disabled."""

    def start(self) -> None:
        """Start screencast (no-op)."""

    def stop(self) -> None:
        """Stop screencast (no-op)."""

    def save(self) -> None:
        """Save screencast (no-op)."""

    def __call__(self, sessionId: str, data: str, metadata: dict) -> None:
        """Handle a screencast frame (no-op)."""


class Screencaster:
    def __init__(self, browser: ChromeBrowser, directory: str):
        self.stopped = False
        self.browser: ChromeBrowser = browser
        self._logger: logging.Logger = browser._logger
        self.directory = pathlib.Path(directory, get_db_name(), "screencasts")
        ts = datetime.now()
        self.frames_dir = self.directory / f"frames-{ts:%Y%m%dT%H%M%S.%f}"
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.frames = []

    def start(self) -> None:
        """Start the Chrome screencast."""
        self._logger.info("Starting screencast")
        self.browser._websocket_send("Page.startScreencast")

    def __call__(self, sessionId: str, data: str, metadata: dict) -> None:
        """Handle a Page.screencastFrame event by saving the frame."""
        self.browser._websocket_send(
            "Page.screencastFrameAck", params={"sessionId": sessionId}
        )
        if self.stopped:
            # if already stopped, drop the frames as we might have removed the directory already
            return
        outfile = self.frames_dir / f"frame_{len(self.frames):05d}.png"
        try:
            outfile.write_bytes(binascii.a2b_base64(data.encode()))
        except FileNotFoundError:
            return
        self.frames.append(
            {"file_path": outfile, "timestamp": metadata.get("timestamp")}
        )

    def stop(self) -> None:
        """Stop the Chrome screencast and discard captured frames."""
        self.browser._websocket_send("Page.stopScreencast")
        self.stopped = True
        if self.frames_dir.is_dir():
            shutil.rmtree(self.frames_dir, ignore_errors=True)

    def save(self) -> None:
        """Stop the screencast and encode captured frames to an MP4."""
        if self.stopped:
            return
        self.browser._websocket_send("Page.stopScreencast")
        # Wait for frames just in case, ideally we'd wait for the Browse.close
        # event or something but that doesn't exist.
        time.sleep(5)
        self.stopped = True
        if not self.frames:
            self._logger.debug("No screencast frames to encode")
            return

        frames, self.frames = self.frames, []
        t = time.time()
        duration = 1 / 24
        concat_script_path = self.frames_dir.with_suffix(".txt")
        with concat_script_path.open("w") as concat_file:
            for f, next_frame in zip_longest(frames, islice(frames, 1, None)):
                frame_file_path = f["file_path"]

                if f["timestamp"] is not None:
                    end_time = next_frame["timestamp"] if next_frame else t
                    duration = end_time - f["timestamp"]
                concat_file.write(f"file '{frame_file_path}'\nduration {duration}\n")
            concat_file.write(
                f"file '{frame_file_path}'"
            )  # needed by the concat plugin

        try:
            ffmpeg_path = find_in_path("ffmpeg")
        except OSError:
            self._logger.runbot("Screencast frames in: %s", self.frames_dir)
            return

        outfile = self.frames_dir.with_suffix(".mp4")
        try:
            subprocess.run(
                [
                    ffmpeg_path,
                    "-y",
                    "-loglevel",
                    "warning",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    concat_script_path,
                    "-vf",
                    "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                    "-c:v",
                    "libx265",
                    "-x265-params",
                    "lossless=1",
                    outfile,
                ],
                preexec_fn=_preexec,
                check=True,
            )
        except subprocess.CalledProcessError:
            self._logger.error(
                "Failed to encode screencast, screencast frames in %s",
                self.frames_dir,
            )
        else:
            concat_script_path.unlink()
            shutil.rmtree(self.frames_dir, ignore_errors=True)
            self._logger.runbot("Screencast in: %s", outfile)


@lru_cache(1)
def _find_executable():
    browser_bin_path = os.environ.get("ODOO_BROWSER_BIN")  # used for testing specific Chrome builds
    if browser_bin_path and pathlib.Path(browser_bin_path).exists():
        return browser_bin_path
    system = platform.system()
    if system == "Linux":
        for bin_ in [
            "google-chrome",
            "chromium",
            "chromium-browser",
            "google-chrome-stable",
        ]:
            try:
                return find_in_path(bin_)
            except OSError:
                continue

    elif system == "Darwin":
        bins = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
        for bin_ in bins:
            if pathlib.Path(bin_).exists():
                return bin_

    elif system == "Windows":
        bins = [
            "%ProgramFiles%\\Google\\Chrome\\Application\\chrome.exe",
            "%ProgramFiles(x86)%\\Google\\Chrome\\Application\\chrome.exe",
            "%LocalAppData%\\Google\\Chrome\\Application\\chrome.exe",
        ]
        for bin_ in bins:
            bin_ = os.path.expandvars(bin_)
            if pathlib.Path(bin_).exists():
                return bin_

    raise unittest.SkipTest("Chrome executable not found")


class Opener(requests.Session):
    """Flush and clear the current transaction before each HTTP request.

    This is necessary when we make requests to the server, as the
    request is made with a test cursor which uses a different cache than this
    transaction.
    """

    def __init__(self, http_case: HttpCase) -> None:
        super().__init__()
        self.test_case = http_case
        self.cr = http_case.cr

    def request(self, *args: Any, **kwargs: Any) -> Any:
        """Flush and clear the cursor before forwarding the request."""
        assert self.test_case.opener == self
        self.cr.flush()
        self.cr.clear()
        with self.test_case.allow_requests():
            return super().request(*args, **kwargs)


class Transport(xmlrpclib.Transport):
    """XML-RPC transport that flushes the test cursor before each request. See :class:`Opener`."""

    def __init__(self, http_case: HttpCase) -> None:
        self.test_case = http_case
        self.cr = http_case.cr
        super().__init__()

    def request(self, *args: Any, **kwargs: Any) -> Any:
        """Flush and clear the cursor before forwarding the XML-RPC request."""
        self.cr.flush()
        self.cr.clear()
        with self.test_case.allow_requests(all_requests=True):
            return super().request(*args, **kwargs)


class JsonRpcException(Exception):
    """Exception raised when a JSON-RPC response contains an error."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


class HttpCase(TransactionCase):
    """Transactional HTTP TestCase with url_open and Chrome headless helpers."""

    registry_test_mode = True
    browser = None
    browser_size = "1366x768"
    touch_enabled = False
    session: odoo.http.Session = None

    _logger: logging.Logger = None

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if cls.registry_test_mode:
            cls.registry_enter_test_mode_cls()

        ICP = cls.env["ir.config_parameter"]
        ICP.set_param("web.base.url", cls.base_url())
        ICP.env.flush_all()
        # v8 api with correct xmlrpc exception handling.
        cls.xmlrpc_url = f"{cls.base_url()}/xmlrpc/2/"
        cls._logger = logging.getLogger("%s.%s" % (cls.__module__, cls.__name__))

    @classmethod
    def base_url(cls) -> str:
        """Return the base URL for the test HTTP server."""
        return f"http://{HOST}:{cls.http_port():d}"

    @classmethod
    def http_port(cls) -> int | None:
        """Return the HTTP server port, or None if the server is not running."""
        if odoo.service.lifecycle.server is None:
            return None
        return odoo.service.lifecycle.server.httpd.server_port

    def setUp(self) -> None:
        super().setUp()

        self._logger = self._logger.getChild(self._testMethodName)

        self.xmlrpc_common = xmlrpclib.ServerProxy(
            self.xmlrpc_url + "common", transport=Transport(self)
        )
        self.xmlrpc_db = xmlrpclib.ServerProxy(
            self.xmlrpc_url + "db", transport=Transport(self)
        )
        self.xmlrpc_object = xmlrpclib.ServerProxy(
            self.xmlrpc_url + "object",
            transport=Transport(self),
            use_datetime=True,
        )
        # setup an url opener helper
        self.opener = Opener(self)
        self.http_key_sequence = itertools.count()

    @contextmanager
    def enter_registry_test_mode(self) -> Generator[None]:
        """No-op: HTTPCase is already in test mode."""
        _logger.warning("HTTPCase is already in test mode")
        yield

    @contextmanager
    def allow_pdf_render(self) -> Generator[None]:
        """No-op: HTTPCase does not require calling allow_pdf_render."""
        _logger.warning("HTTPCase does not require calling allow_pdf_render")
        yield

    @contextmanager
    def allow_requests(self, browser: ChromeBrowser | None = None, all_requests=False):
        """
        Allows HTTP requests for the scope of the context.

        Params:
            browser (ChromeBrowser | None): if given, add the cookie to the browser.
            all_requests (bool): if True, allows all requests regardless of cookie.
        """
        with ExitStack() as defer:
            defer.enter_context(release_test_lock())
            if all_requests:
                self.http_request_allow_all = True
            new_key = f"{self.canonical_tag}__{next(self.http_key_sequence)}"
            defer.enter_context(patch.object(self, "http_request_key", new_key))
            old_cookie = self.opener.cookies.get(TEST_CURSOR_COOKIE_NAME)
            if old_cookie:
                defer.callback(
                    self.opener.cookies.set, TEST_CURSOR_COOKIE_NAME, old_cookie
                )
            else:
                defer.callback(self.opener.cookies.pop, TEST_CURSOR_COOKIE_NAME, None)
            self.opener.cookies[TEST_CURSOR_COOKIE_NAME] = new_key
            if browser:
                # http_only keeps this cookie out of document.cookie: only the
                # HTTP worker needs it (to match a request to its test cursor),
                # and a JS-visible cookie would pollute HOOT's MockCookie jar.
                browser.set_cookie(
                    TEST_CURSOR_COOKIE_NAME,
                    self.http_request_key,
                    "/",
                    HOST,
                    http_only=True,
                )
            yield

    def parse_http_location(self, location: str | None) -> Any:
        """Parse a Location HTTP header found in 201/3xx responses.

        Return the corresponding parsed URL object. The scheme/host
        are taken from ``base_url()`` in case they are missing from the header.
        """
        if not location:
            return urlsplit("")
        s = urlsplit(urljoin(self.base_url(), location))
        # normalise query parameters
        return s._replace(query=urlencode(parse_qsl(s.query)))

    def assertURLEqual(
        self, test_url: str, truth_url: str, message: str | None = None
    ) -> None:
        """Assert that two URLs are equivalent.

        If any URL is missing a scheme and/or host, assume the same scheme/host as ``base_url()``.
        """
        self.assertEqual(
            self.parse_http_location(test_url),
            self.parse_http_location(truth_url),
            message,
        )

    def build_rpc_payload(self, params: dict | None = None) -> dict:
        """Build a properly structured JSON-RPC 2.0 payload."""
        return {
            "jsonrpc": "2.0",
            "method": "call",
            "id": str(uuid4()),
            "params": params or {},
        }

    def url_open(
        self,
        url: str,
        data: Any = None,
        files: Any = None,
        timeout: int = 12,
        headers: dict | None = None,
        json: Any = None,
        params: dict | None = None,
        allow_redirects: bool = True,
        cookies: dict | None = None,
        method: str | None = None,
    ) -> Any:
        if not method and (data or files or json):
            method = "POST"
        method = method or "GET"
        if url.startswith("/"):
            url = self.base_url() + url
        return self.opener.request(
            method,
            url,
            params=params,
            data=data,
            json=json,
            files=files,
            timeout=timeout,
            headers=headers,
            cookies=cookies,
            allow_redirects=allow_redirects,
        )

    def _wait_remaining_requests(self, timeout: int = 10) -> None:
        """Wait for all in-flight HTTP request threads to finish."""

        def get_http_request_threads() -> list[threading.Thread]:
            return [
                t
                for t in threading.enumerate()
                if t.name.startswith("odoo.service.http.request.")
            ]

        start_time = time.time()
        request_threads = get_http_request_threads()
        if not request_threads:
            return

        self._logger.info("waiting for threads: %s", request_threads)

        for thread in request_threads:
            thread.join(timeout - (time.time() - start_time))

        request_threads = get_http_request_threads()
        for thread in request_threads:
            self._logger.info(
                "Stop waiting for thread %s handling request for url %s",
                thread.name,
                getattr(thread, "url", "<UNKNOWN>"),
            )

        if request_threads:
            self._logger.info("remaining requests")
            odoo.tools.misc.dumpstacks()

    def logout(self, keep_db: bool = True) -> None:
        """Log out the current session."""
        self.session.logout(keep_db=keep_db)
        odoo.http.root.session_store.save(self.session)

    def authenticate(
        self,
        user: str | None,
        password: str | None,
        *,
        browser: ChromeBrowser | None = None,
        session_extra: dict | None = None,
    ) -> Any:
        if getattr(self, "session", None):
            odoo.http.root.session_store.delete(self.session)

        self.session = session = odoo.http.root.session_store.new()
        session.update(
            odoo.http.get_default_session(),
            db=get_db_name(),
            # In order to avoid perform a query to each first `url_open`
            # in a test (insert `res.device.log`).
            _trace_disable=True,
        )
        session.context["lang"] = odoo.http.DEFAULT_LANG

        if session_extra:
            if extra_ctx := session_extra.pop("context", None):
                session.context.update(extra_ctx)
            session.update(session_extra)

        if user:  # if authenticated
            # Flush and clear the current transaction.  This is useful, because
            # the call below opens a test cursor, which uses a different cache
            # than this transaction.
            self.cr.flush()
            self.cr.clear()

            def patched_check_credentials(self, credential, env):
                return {
                    "uid": self.id,
                    "auth_method": "password",
                    "mfa": "default",
                }

            # patching to speedup the check in case the password is hashed with many hashround + avoid to update the password
            with patch(
                "odoo.addons.base.models.res_users.ResUsersPatchedInTest._check_credentials",
                new=patched_check_credentials,
            ):
                credential = {
                    "login": user,
                    "password": password,
                    "type": "password",
                }
                auth_info = self.env["res.users"].authenticate(
                    credential, {"interactive": False}
                )
            uid = auth_info["uid"]
            env = api.Environment(self.cr, uid, {})
            session.uid = uid
            session.login = user
            session.session_token = uid and security.compute_session_token(session, env)
            session.context = dict(env["res.users"].context_get())

        odoo.http.root.session_store.save(session)
        # Reset the opener: turns out when we set cookies['foo'] we're really
        # setting a cookie on domain='' path='/'.
        #
        # But then our friendly neighborhood server might set a cookie for
        # domain='localhost' path='/' (with the same value) which is considered
        # a *different* cookie following ours rather than the same.
        #
        # When we update our cookie, it's done in-place, so the server-set
        # cookie is still present and (as it follows ours and is more precise)
        # very likely to still be used, therefore our session change is ignored.
        #
        # An alternative would be to set the cookie to None (unsetting it
        # completely) or clear-ing session.cookies.
        self.opener = Opener(self)
        self.opener.cookies.set("session_id", session.sid, domain=HOST)
        if browser:
            self._logger.info("Setting session cookie in browser")
            # http_only mirrors the server's httponly session_id cookie; JS never
            # reads it, and leaving it JS-visible would pollute HOOT's MockCookie jar.
            browser.set_cookie(
                "session_id", session.sid, "/", HOST, http_only=True
            )

        return session

    def fetch_proxy(self, url: str) -> dict:
        """Return a synthetic response for external Chrome requests.

        Called every time Chrome makes a request outside the local network.
        """

        if "https://fonts.googleapis.com/css" in url:
            _logger.info(
                "External chrome request during tests: Return empty file for %s",
                url,
            )
            return self.make_fetch_proxy_response(
                ""
            )  # return empty css file, we don't care

        _logger.info("External chrome request during tests: returning 404 for %s", url)
        return {
            "body": "",
            "responseCode": 404,
            "responseHeaders": [],
        }

    def make_fetch_proxy_response(self, content: str | bytes, code: int = 200) -> dict:
        """Build a Fetch proxy response dict for Chrome DevTools."""
        if isinstance(content, str):
            content = content.encode()
        return {
            "body": base64.b64encode(content).decode(),
            "responseCode": code,
            "responseHeaders": [
                {"name": "access-control-allow-origin", "value": "*"},
                {"name": "cache-control", "value": "public, max-age=10000"},
            ],
        }

    def browser_js(
        self,
        url_path,
        code,
        ready="",
        login=None,
        timeout=60,
        cookies=None,
        error_checker=None,
        watch=False,
        success_signal=DEFAULT_SUCCESS_SIGNAL,
        debug=False,
        cpu_throttling=None,
        **kw,
    ):
        """Test JavaScript code running in the browser.

        To signal success test do: `console.log()` with the expected `success_signal`. Default is "test successful"
        To signal test failure raise an exception or call `console.error` with a message.
        Test will stop when a failure occurs if `error_checker` is not defined or returns `True` for this message

        :param string url_path: URL path to load the browser page on
        :param string code: JavaScript code to be executed
        :param string ready: JavaScript object to wait for before proceeding with the test
        :param string login: logged in user which will execute the test. e.g. 'admin', 'demo'
        :param int timeout: maximum time to wait for the test to complete (in seconds). Default is 60 seconds
        :param dict cookies: dictionary of cookies to set before loading the page
        :param error_checker: function to filter failures out.
            If provided, the function is called with the error log message, and if it returns `False` the log is ignored and the test continue
            If not provided, every error log triggers a failure
        :param bool watch: open a new browser window to watch the test execution
        :param string success_signal: string signal to wait for to consider the test successful
        :param bool debug: automatically open a fullscreen Chrome window with opened devtools and a debugger breakpoint set at the start of the tour.
            The tour is ran with the `debug=assets` query parameter. When an error is thrown, the debugger stops on the exception.
        :param int cpu_throttling: CPU throttling rate as a slowdown factor (1 is no throttle, 2 is 2x slowdown, etc)
        """
        if not self.env.registry.loaded:
            self._logger.warning("HttpCase test should be in post_install only")

        # increase timeout if coverage is running
        if any(
            f.filename.endswith("/coverage/execfile.py")
            for f in inspect.stack()
            if f.filename
        ):
            timeout = timeout * 1.5

        if debug is not False:
            watch = True
            timeout = 1e6
        if watch:
            self._logger.warning("watch mode is only suitable for local testing")

        browser = ChromeBrowser(
            self, headless=not watch, success_signal=success_signal, debug=debug
        )
        with (
            self.allow_requests(browser=browser),
            contextlib.ExitStack() as atexit,
        ):
            atexit.callback(self._wait_remaining_requests)
            if "bus.bus" in self.env.registry:
                from odoo.addons.bus.models.bus import BusBus
                from odoo.addons.bus.websocket import (
                    CloseCode,
                    WebsocketConnectionHandler,
                    _kick_all,
                )

                atexit.callback(_kick_all, CloseCode.KILL_NOW)
                original_send_one = BusBus._sendone

                def sendone_wrapper(self, target, notification_type, message):
                    original_send_one(self, target, notification_type, message)
                    self.env.cr.precommit.run()  # Trigger the creation of bus.bus records
                    self.env.cr.postcommit.run()  # Trigger notification dispatching

                atexit.enter_context(patch.object(BusBus, "_sendone", sendone_wrapper))
                atexit.enter_context(
                    patch.object(
                        WebsocketConnectionHandler,
                        "websocket_allowed",
                        return_value=True,
                    )
                )

            self.authenticate(login, login, browser=browser)
            # Flush and clear the current transaction.  This is useful in case
            # we make requests to the server, as these requests are made with
            # test cursors, which uses different caches than this transaction.
            self.cr.flush()
            self.cr.clear()
            url = urljoin(self.base_url(), url_path)
            if watch:
                parsed = urlsplit(url)
                qs = dict(parse_qsl(parsed.query))
                qs["watch"] = "1"
                if debug is not False:
                    qs["debug"] = "assets"
                url = urlunsplit(parsed._replace(query=urlencode(qs)))
            self._logger.info('Open "%s" in browser', url)

            browser.screencaster.start()
            if cookies:
                for name, value in cookies.items():
                    browser.set_cookie(name, value, "/", HOST)

            cpu_throttling_os = os.environ.get(
                "ODOO_BROWSER_CPU_THROTTLING"
            )  # used by dedicated runbot builds
            cpu_throttling = (
                int(cpu_throttling_os) if cpu_throttling_os else cpu_throttling
            )

            if cpu_throttling:
                _logger.log(
                    logging.INFO if cpu_throttling_os else logging.WARNING,
                    "CPU throttling mode is only suitable for local testing - "
                    "Throttling browser CPU to %sx slowdown and extending timeout to %s sec",
                    cpu_throttling,
                    timeout,
                )
                browser.throttle(cpu_throttling)

            browser.navigate_to(url, wait_stop=not bool(ready))
            atexit.callback(browser.stop)

            # Needed because tests like test01.js (qunit tests) are passing a ready
            # code = ""
            self.assertTrue(
                browser._wait_ready(ready),
                'The ready "%s" code was always falsy' % ready,
            )

            error = False
            try:
                browser._wait_code_ok(code, timeout, error_checker=error_checker)
            except ChromeBrowserException as chrome_browser_exception:
                error = chrome_browser_exception
            if error:  # dont keep initial traceback, keep that outside of except
                if code:
                    message = 'The test code "%s" failed' % code
                else:
                    message = "Some js test failed"
                self.fail("%s\n\n%s" % (message, error))

    def start_tour(
        self,
        url_path: str,
        tour_name: str,
        step_delay: int | None = None,
        **kwargs: Any,
    ) -> None:
        """Wrapper for `browser_js` to start the given `tour_name` with the
        optional delay between steps `step_delay`. Other arguments from
        `browser_js` can be passed as keyword arguments."""
        options = {
            "stepDelay": step_delay or 0,
            "keepWatchBrowser": kwargs.get("watch", False),
            "debug": kwargs.get("debug", False),
            "startUrl": url_path,
            "delayToCheckUndeterminisms": kwargs.pop(
                "delay_to_check_undeterminisms",
                int(os.getenv("ODOO_TOUR_DELAY_TO_CHECK_UNDETERMINISMS", "0")) or 0,
            ),
        }
        code = kwargs.pop(
            "code", f"odoo.startTour({tour_name!r}, {json.dumps(options)})"
        )
        ready = kwargs.pop("ready", f"odoo.isTourReady({tour_name!r})")
        timeout = kwargs.pop("timeout", 60)

        if step_delay is not None:
            self._logger.warning("step_delay is only suitable for local testing")
        if options["delayToCheckUndeterminisms"] > 0:
            timeout = timeout + 1000 * options["delayToCheckUndeterminisms"]
            _logger.runbot(
                "Tour %s is launched with mode: check for undeterminisms.",
                tour_name,
            )
        Users = self.registry["res.users"]

        def setup(_):
            Users.tour_enabled = False

        with (
            patch.object(Users, "tour_enabled", False),
            patch.object(Users, "_post_model_setup__", setup),
            patch.object(Users, "_compute_tour_enabled", lambda _: None),
        ):
            self.browser_js(
                url_path=url_path,
                code=code,
                ready=ready,
                timeout=timeout,
                success_signal="tour succeeded",
                **kwargs,
            )

    def profile(self, **kwargs: Any) -> Any:
        """Return a nested profiler that profiles both the test and all HTTP requests."""
        sup = super()
        _profiler = sup.profile(**kwargs)

        def route_profiler(request):
            _route_profiler = sup.profile(
                description=request.httprequest.full_path, db=_profiler.db
            )
            _profiler.sub_profilers.append(_route_profiler)
            return _route_profiler

        return profiler.Nested(
            _profiler,
            patch(
                "odoo.http.Request._get_profiler_context_manager",
                route_profiler,
            ),
        )

    def get_method_additional_tags(self, test_method: Callable | None) -> list[str]:
        """Guess if the test_method is a tour and add an ``is_tour`` tag."""
        additional_tags = super().get_method_additional_tags(test_method)
        if (
            odoo.tools.config["test_tags"]
            and "is_tour" in odoo.tools.config["test_tags"]
        ):
            method_source = inspect.getsource(test_method)
            if "self.start_tour" in method_source:
                additional_tags.append("is_tour")
        return additional_tags

    def make_jsonrpc_request(
        self,
        route: str,
        params: dict | None = None,
        headers: dict | None = None,
        cookies: dict | None = None,
        timeout: int = 12,
    ) -> Any:
        """Make a JSON-RPC request to the server.

        :raises requests.HTTPError: if one occurred
        :raises JsonRpcException: if the response contains an error
        """
        response = self.opener.post(
            urljoin(self.base_url(), route),
            json={
                "id": 0,
                "jsonrpc": "2.0",
                "method": "call",
                "params": params or {},
            },
            headers=headers,
            cookies=cookies,
            timeout=timeout,
        )
        response.raise_for_status()
        decoded_response = response.json()
        if "error" in decoded_response:
            raise JsonRpcException(
                code=decoded_response["error"]["code"],
                message=decoded_response["error"]["data"]["name"],
            )
        # workaround: JsonRPCDispatcher is broken and may send neither result nor error
        return decoded_response.get("result")


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


freezegun.freeze_time = freeze_time
