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
import types
import unittest
import warnings
from collections import defaultdict, deque
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from functools import partial, wraps
from itertools import zip_longest
from typing import TYPE_CHECKING, Any, Self, cast
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
from odoo.libs.password import CryptContext
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
from odoo.tools.xml_utils import _check_xml

from . import case
from .browser import DEFAULT_SUCCESS_SIGNAL, ChromeBrowser, ChromeBrowserException
from .cursor import TestCursor
from .utils import HOST, env_int, get_db_name, save_test_file

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable

    import odoo.addons.base
    from .result import OdooTestResult


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
    "release_stranded_test_cursors",
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
    model = bound_method.__self__
    ormcache_instance = bound_method.__cache__
    cache = model.pool.ormcache_lrus[ormcache_instance.cache_name]
    key = ormcache_instance.key(model, *args, **kwargs)
    counter = _COUNTERS[model.pool.db_name, ormcache_instance.method]
    return cache, key, counter


ADMIN_USER_ID = api.SUPERUSER_ID

TEST_CURSOR_COOKIE_NAME = "test_request_key"


def skip_if_dev_mode(*flags: str) -> None:
    dev_mode = config["dev_mode"]
    if active := [flag for flag in flags if flag in dev_mode]:
        raise unittest.SkipTest(
            f"--dev={','.join(active)} disables the behaviour under test"
        )


standalone_tests = defaultdict(list)


class RegistryRLock(threading._RLock):
    @property
    def count(self) -> int:
        return self._count


_registry_test_lock = RegistryRLock()
_registry_test_lock.acquire()


def current_test_tag() -> str:
    return getattr(odoo.modules.module.current_test, "canonical_tag", "<no test>")


@contextmanager
def release_test_lock() -> Generator[None]:
    try:
        _registry_test_lock.release()
        yield
    finally:
        if not _registry_test_lock.acquire(timeout=60):
            sys.exit(
                f"Could not re-acquire the registry lock during "
                f"{current_test_tag()}, exiting..."
            )


def standalone(*tags: str) -> Callable[[Callable], Callable]:

    def register(func: Callable) -> Callable:
        if func.__module__.startswith("odoo.addons."):
            module = func.__module__.split(".")[2]
            standalone_tests[module].append(func)
        for tag in tags:
            standalone_tests[tag].append(func)
        standalone_tests["all"].append(func)
        return func

    return register


def test_xsd(url=None, path=None, skip=False):

    def decorator(func):
        @wraps(func)
        def wrapped_f(self, *args, **kwargs):
            if skip:
                raise unittest.SkipTest(
                    skip if isinstance(skip, str) else "XSD validation disabled"
                )
            xmls = func(self, *args, **kwargs)
            _check_xml(self.env, url, path, xmls)

        return wrapped_f

    return decorator


def new_test_user(env, login="", groups="base.group_user", context=None, **kwargs):
    """Create a res.users, filling the fields most odoo operations require.

    ``kwargs`` is propagated to the create. Defaults that are *not* obvious:

    * ``name``     -- "login (groups)", because it is required;
    * ``password`` -- the login padded to 8 characters;
    * ``email``    -- the login if it is a valid address, else the generated
      ``x.x@example.com`` where x is the login's first letter.

    That last one is deliberate (and upstream), not a typo -- but note the
    hazard it creates: every login sharing a first letter shares an address,
    so ``new_test_user(env, "bert")`` and ``new_test_user(env, "bob")`` both
    get ``b.b@example.com``. Anything resolving partners by email
    (``_partner_find_from_emails``) will see them as one. Pass ``email``
    explicitly when a test depends on recipients being distinct.
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
    if not create_values.get("name"):
        create_values["name"] = f"{login} ({groups})"
    if not create_values.get("password"):
        create_values["password"] = login + "x" * (8 - len(login))
    if "email" not in create_values:
        if single_email_re.match(login):
            create_values["email"] = login
        else:
            create_values["email"] = f"{login[0]}.{login[0]}@example.com"
    if "company_id" in create_values and "company_ids" not in create_values:
        create_values["company_ids"] = [(4, create_values["company_id"])]

    return env["res.users"].with_context(**context).create(create_values)


def release_stranded_test_cursors(owner: str = "") -> int:
    """Close out any TestCursor left in the stack, and give its lock back.

    Releasing is not optional. ``TestCursor.__init__`` acquires
    ``_registry_test_lock`` and ``close()`` is the only release, so a cursor
    stranded here would hold an acquisition for the life of the process. Since
    ``release_test_lock()`` releases exactly one, the count would then never
    reach zero again and *every later HttpCase request* would block for
    ``test_cursor_lock_timeout`` and fail with "Unable to acquire lock for test
    cursor after 20s" -- attributed to whichever test ran next rather than to
    the one that stranded it.

    Returns how many were stranded, so a caller can assert on it.
    """
    stranded = TestCursor._cursors_stack
    for cursor in stranded:
        _logger.warning(
            "A cursor was remaining in the TestCursor stack at the end of %s; "
            "releasing its registry lock",
            owner or "the test",
        )
        cursor._closed = True
        cursor._lock.release()
    count = len(stranded)
    TestCursor._cursors_stack = []
    return count


def loaded_demo_data(env: api.Environment) -> bool:
    return bool(env.ref("base.user_demo", raise_if_not_found=False))


class RecordCapturer:
    def __init__(self, model: Any, domain: list | None = None) -> None:
        self._model = model
        self._domain = domain or []

    def __enter__(self) -> Self:
        self._before = self._model.search(self._domain, order="id")
        self._after = None
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: types.TracebackType | None,
    ) -> None:
        if exc_type is None:
            self._after = self._model.search(self._domain, order="id") - self._before

    @property
    def records(self) -> Any:
        if self._after is None:
            return self._model.search(self._domain, order="id") - self._before
        return self._after


def _enter_context(cm: Any, addcleanup: Callable) -> Any:
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


def _query_text(query: Any) -> str:
    if isinstance(query, SQL):
        return query.code
    if isinstance(query, str):
        return query
    if isinstance(query, bytes):
        return query.decode()
    return str(query)


def _copy_from_text(table, columns, *args, **kwargs) -> str:
    columns_sql = ", ".join(f'"{column}"' for column in columns)
    return f'COPY "{table}" ({columns_sql}) FROM STDIN'


_STATEMENT_RECORDERS = {
    "execute": lambda query, *args, **kwargs: _query_text(query),
    "executemany": lambda query, *args, **kwargs: _query_text(query),
    "copy": lambda statement, *args, **kwargs: _query_text(statement),
    "copy_from": _copy_from_text,
}

_DELEGATING_STATEMENTS = {"execute_values"}


class BlockedRequest(requests.exceptions.ConnectionError):
    pass


_super_send = requests.Session.send


class BaseCase(case.TestCase):
    registry: Registry = None
    env: api.Environment = None
    cr: Cursor = None

    test_tags: set[str] | None = None

    test_module: str = ""

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if cls.__module__.startswith("odoo.addons."):
            if cls.test_tags is None:
                cls.test_tags = {"standard", "at_install"}
            cls.test_module = cls.__module__.split(".")[2]

    longMessage = True
    warm = True

    _tests_run_count = env_int("ODOO_TEST_FAILURE_RETRIES", 0) + 1

    _registry_patched = False
    _registry_readonly_enabled = True
    test_cursor_lock_timeout: int = 20

    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        self.addTypeEqualityFunc(etree._Element, self.assertTreesEqual)
        self.addTypeEqualityFunc(html.HtmlElement, self.assertTreesEqual)
        if methodName != "runTest":
            self.test_tags = (self.test_tags or set()) | set(
                self.get_method_additional_tags(getattr(self, methodName))
            )

    @classmethod
    def _request_handler(cls, s: Session, r: PreparedRequest, /, **kw):
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

    def run(self, result: OdooTestResult) -> None:
        testMethod = getattr(self, self._testMethodName)

        if getattr(testMethod, "_retry", True) and getattr(self, "_retry", True):
            tests_run_count = self._tests_run_count
        else:
            tests_run_count = 1
            _logger.info("Auto retry disabled for %s", self)

        for retry in range(tests_run_count):
            result.had_failure = False
            if retry:
                _logger.runbot(f"Retrying a failed test: {self}")
            with ExitStack() as attempt:
                if retry:
                    attempt.enter_context(result.retry())

                if retry == tests_run_count - 1:
                    super().run(cast("TestResult", result))
                    if not result.wasSuccessful() and BaseCase._tests_run_count != 1:
                        _logger.runbot("Disabling auto-retry after a failed test")
                        BaseCase._tests_run_count = 1
                    break

                attempt.enter_context(warnings.catch_warnings())
                attempt.enter_context(result.soft_fail())
                quiet_log = attempt.enter_context(lower_logging(25, logging.INFO))
                super().run(cast("TestResult", result))
                if not (result.had_failure or quiet_log.had_error_log):
                    break

    @classmethod
    def setUpClass(cls) -> None:
        def check_remaining_processes() -> None:
            current_process = psutil.Process()
            children = current_process.children(recursive=False)
            for child in children:
                _logger.warning("A child process was found, terminating it: %s", child)
                child.terminate()
            psutil.wait_procs(children, timeout=10)

        cls.addClassCleanup(check_remaining_processes)

        def check_remaining_patchers():
            for patcher in list(_patch._active_patches):
                if hasattr(patcher, "target"):
                    description = f"{patcher.target}.{patcher.attribute}"
                else:
                    description = f"dict {getattr(patcher, 'in_dict', patcher)!r}"
                _logger.warning(
                    "A patcher (targeting %s) was remaining active at the end of %s, disabling it...",
                    description,
                    cls.__name__,
                )
                patcher.stop()

        cls.addClassCleanup(check_remaining_patchers)

        def close_sass():
            try:
                from odoo.tools.sass_embedded import close_sass_compiler

                close_sass_compiler()
            except ImportError:
                pass

        cls.addClassCleanup(close_sass)

        def close_esm_lexer():
            try:
                from odoo.tools.assets.esm_lexer import close_lexer_worker

                close_lexer_worker()
            except ImportError:
                pass

        cls.addClassCleanup(close_esm_lexer)
        super().setUpClass()
        if "standard" in cls.test_tags or "click_all" in cls.test_tags:
            patcher = patch.object(
                requests.sessions.Session,
                "send",
                # The lambda is load-bearing: _request_handler is a
                # classmethod, so passing it directly would install an already
                # bound object as Session.send and shift (s, r) by one.
                lambda s, r, **kw: cls._request_handler(s, r, **kw),  # noqa: PLW0108  classmethod would bind and shift (s, r)
            )
            patcher.start()
            cls.addClassCleanup(patcher.stop)

    def setUp(self) -> None:
        super().setUp()
        self.http_request_key: str = ""
        self.http_request_allow_all: bool = False
        self.addCleanup(
            setattr,
            type(self),
            "_registry_readonly_enabled",
            self._registry_readonly_enabled,
        )

    def cursor(self) -> Cursor:
        return self.registry.cursor()

    @property
    def uid(self):
        return self.env.uid

    @uid.setter
    def uid(self, user):
        self.env = self.env(user=user)
        self.env.transaction.default_env = self.env

    def ref(self, xid: str) -> int:
        return self.browse_ref(xid).id

    def browse_ref(self, xid: str) -> Any:
        assert "." in xid, (
            "this method requires a fully qualified parameter, in the following form: 'module.identifier'"
        )
        return self.env.ref(xid)

    def patch(self, obj: Any, key: str, val: Any) -> None:
        patcher = patch.object(obj, key, val)
        patcher.start()
        self.addCleanup(patcher.stop)

    @classmethod
    def classPatch(cls, obj: Any, key: str, val: Any) -> None:
        patcher = patch.object(obj, key, val)
        patcher.start()
        cls.addClassCleanup(patcher.stop)

    def startPatcher(self, patcher: Any) -> Any:
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    @classmethod
    def startClassPatcher(cls, patcher: Any) -> Any:
        mock = patcher.start()
        cls.addClassCleanup(patcher.stop)
        return mock

    def enterContext(self, cm: Any) -> Any:
        return _enter_context(cm, self.addCleanup)

    @classmethod
    def enterClassContext(cls, cm: Any) -> Any:
        return _enter_context(cm, cls.addClassCleanup)

    @contextmanager
    def with_user(self, login: str) -> Generator[None]:
        old_uid = self.uid
        old_env = self.env
        try:
            user = self.env["res.users"].sudo().search([("login", "=", login)])
            assert user, f"Login {login} not found"
            self.uid = user.id
            yield
        finally:
            self.uid = old_uid
            self.env = old_env

    @contextmanager
    def debug_mode(self) -> Generator[None]:
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
        with ExitStack() as init:
            if self.env:
                init.enter_context(self.env.cr.savepoint())
                if isinstance(exception, tuple):
                    clear_cache = any(issubclass(exc, AccessError) for exc in exception)
                else:
                    clear_cache = issubclass(exception, AccessError)
                if clear_cache:
                    self.env.cr.clear()

            with ExitStack() as inner:
                cm = inner.enter_context(super().assertRaises(exception, msg=msg))
                inner.push(init.pop_all())

                yield cm

    def assertRaises(
        self,
        exception: type[BaseException],
        func: Callable | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if func:
            with self._assertRaises(exception):
                func(*args, **kwargs)
        else:
            return self._assertRaises(exception, **kwargs)
        return None

    def _patchExecute(self, actual_queries, flush=True):

        def recorded(name, describe):
            original = getattr(Cursor, name)

            def wrapper(cr, *args, **kwargs):
                actual_queries.append(describe(*args, **kwargs))
                return original(cr, *args, **kwargs)

            return patch.object(Cursor, name, wrapper)

        if flush:
            self.env.flush_all()
            self.env.cr.flush()

        with ExitStack() as patches:
            for name, describe in _STATEMENT_RECORDERS.items():
                patches.enter_context(recorded(name, describe))
            patches.enter_context(
                patch.object(self.env.registry, "unaccent", lambda x: x)
            )
            yield actual_queries
            if flush:
                self.env.flush_all()
                self.env.cr.flush()

    @staticmethod
    def _normalize_query(query: str) -> str:
        normalized = "".join(query.lower().split())
        return re.sub(r"\((?:%s|default)(?:,(?:%s|default))*\)", "(%s)", normalized)

    def _assert_queries(
        self,
        expected: list[str],
        actual_queries: list[str],
        compare: Callable[[str, str], None],
    ) -> None:
        """Shared tail of assertQueries/assertQueriesContain.

        Neither is a subset check: the query *count* must match exactly, and
        `compare` decides how each pair is matched.
        """
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
            compare(actual_query, expect_query)

    @contextmanager
    def assertQueries(
        self, expected: list[str], flush: bool = True
    ) -> Generator[list[str]]:
        actual_queries = []

        yield from self._patchExecute(actual_queries, flush)

        def equals(actual_query: str, expect_query: str) -> None:
            self.assertEqual(
                self._normalize_query(actual_query),
                self._normalize_query(expect_query),
                "\n---- actual query:\n%s\n---- not like:\n%s"
                % (actual_query, expect_query),
            )

        self._assert_queries(expected, actual_queries, equals)

    @contextmanager
    def assertQueriesContain(
        self, expected: list[str], flush: bool = True
    ) -> Generator[list[str]]:
        actual_queries = []

        yield from self._patchExecute(actual_queries, flush)

        def contains(actual_query: str, expect_query: str) -> None:
            self.assertIn(
                self._normalize_query(expect_query),
                self._normalize_query(actual_query),
                "\n---- actual query:\n%s\n---- doesn't contain:\n%s"
                % (actual_query, expect_query),
            )

        self._assert_queries(expected, actual_queries, contains)

    @contextmanager
    def assertQueryCount(
        self, default: int = 0, flush: bool = True, **counters: int
    ) -> Generator[None]:
        if self.warm:
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
                    caller = inspect.stack(0)[2]
                    filename, linenum, funcname = (
                        caller.filename,
                        caller.lineno,
                        caller.function,
                    )
                    filename = filename.replace("\\", "/")
                    if "/odoo/addons/" in filename:
                        filename = filename.rsplit("/odoo/addons/", 1)[1]
                    if count > expected:
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
                # None first: it is the caller's way of writing "falsy", and
                # float(None)/int(None) would raise TypeError here rather than
                # letting the comparison below report the real difference.
                if vs[f] is None:
                    r[f] = False
                elif t in ("one2many", "many2many"):
                    r[f] = sorted(vs[f])
                elif t == "float":
                    r[f] = float(vs[f])
                elif t == "integer":
                    r[f] = int(vs[f])
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

        diffMsg = "".join(
            difflib.unified_diff(
                pprint.pformat(expected_reformatted).splitlines(keepends=True),
                pprint.pformat(record_reformatted).splitlines(keepends=True),
                fromfile="expected",
                tofile="records",
            )
        )
        self.fail(self._formatMessage(None, standardMsg + "\n" + diffMsg))

    def assertItemsEqual(self, a: Any, b: Any, msg: str | None = None) -> None:
        self.assertCountEqual(a, b, msg=msg)

    def assertTreesEqual(self, n1: Any, n2: Any, msg: str | None = None) -> None:
        self.assertIsNotNone(n1, msg)
        self.assertIsNotNone(n2, msg)
        self.assertEqual(n1.tag, n2.tag, msg)
        self.assertEqual(dict(n1.attrib), dict(n2.attrib), msg)
        self.assertEqual((n1.text or "").strip(), (n2.text or "").strip(), msg)
        self.assertEqual((n1.tail or "").strip(), (n2.tail or "").strip(), msg)

        for c1, c2 in zip_longest(n1, n2):
            self.assertTreesEqual(c1, c2, msg)

    def _assertXMLEqual(
        self, original: str, expected: str, parser: str = "xml"
    ) -> None:
        self.maxDiff = 10000
        if original:
            original = _normalize_arch_for_assert(original, parser)
        if expected:
            expected = _normalize_arch_for_assert(expected, parser)
        self.assertEqual(original, expected)

    def assertXMLEqual(self, original: str, expected: str) -> None:
        return self._assertXMLEqual(original, expected)

    def assertHTMLEqual(self, original: str, expected: str) -> None:
        return self._assertXMLEqual(original, expected, "html")

    def profile(self, description: str = "", **kwargs: Any) -> Any:
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

        def _patched_cursor(readonly: bool = False):
            return TestCursor(
                cr,
                _registry_test_lock,
                readonly and cls._registry_readonly_enabled,
            )

        patches = [
            patch.object(registry, "cursor", _patched_cursor),
            patch.object(Registry, "_lock", DummyRLock()),
            patch.object(registry, "setup_signaling", return_value=None),
            patch.object(registry, "check_signaling", return_value=registry),
        ]

        try:
            from odoo.addons.bus import websocket as bus_websocket
        except ImportError:
            pass
        else:
            og_db_connect = bus_websocket.db_connect

            def _patched_ws_db_connect(to, allow_uri=False, readonly=False):
                if to == cr.dbname:

                    class _TestConnection:
                        def cursor(self):
                            return _patched_cursor(readonly)

                    return _TestConnection()
                return og_db_connect(to, allow_uri=allow_uri, readonly=readonly)

            patches.append(
                patch.object(bus_websocket, "db_connect", _patched_ws_db_connect)
            )

        return patches

    @classmethod
    def _registry_enter_test_mode(cls, *, cr: Cursor) -> None:
        assert not cls._registry_patched, "Can only patch registry once"
        assert cr, "No cursor"
        assert cls.registry, "No registry"

        cls.registry_patches = cls._registry_test_mode_patches(
            cr=cr,
            registry=cls.registry,
        )
        for p in cls.registry_patches:
            p.start()
        cls._registry_patched = True

    @classmethod
    def registry_enter_test_mode_cls(cls) -> None:
        cls._registry_enter_test_mode(cr=cls.cr)
        cls.addClassCleanup(cls.registry_leave_test_mode)

    def registry_enter_test_mode(
        self, *, cr: Cursor | None = None, register_cleanup: bool = True
    ) -> None:
        # Same work as registry_enter_test_mode_cls, differing only in which
        # cursor is used and whether the undo is a test or a class cleanup.
        type(self)._registry_enter_test_mode(cr=cr or self.cr)
        if register_cleanup:
            self.addCleanup(self.registry_leave_test_mode)

    @classmethod
    def registry_leave_test_mode(cls) -> None:
        assert cls._registry_patched, "Registry is not patched"

        for p in cls.registry_patches:
            p.stop()
        cls.registry_patches.clear()
        cls._registry_patched = False

    @classmethod
    def set_registry_readonly_mode(cls, enabled: bool) -> None:
        assert cls._registry_patched, "Registry is not patched"

        cls._registry_readonly_enabled = enabled

    def assertCanOpenTestCursor(self) -> None:
        if odoo.modules.module.current_test is not self:
            message = f"Trying to open a test cursor for {self.canonical_tag} while already in a test {current_test_tag()}"
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

    _SOURCE_TAGS: dict[str, str] = {"is_query_count": "self.assertQueryCount"}
    """Tags derived by grepping a test's own source: {tag: needle}.

    Subclasses extend the mapping rather than overriding the method, so the
    source is read once however many of these tags are being selected.
    """

    def get_method_additional_tags(self, test_method: Callable | None) -> list[str]:
        selected = odoo.tools.config["test_tags"] or ""
        wanted = {
            tag: needle for tag, needle in self._SOURCE_TAGS.items() if tag in selected
        }
        if not wanted or test_method is None:
            return []
        try:
            method_source = inspect.getsource(test_method)
        except OSError, TypeError:
            # dynamically built test methods have no retrievable source
            return []
        return [tag for tag, needle in wanted.items() if needle in method_source]


class Like:
    def __init__(self, pattern: str) -> None:
        self.pattern = pattern
        self.regex = ".*".join(
            [re.escape(part.strip()) for part in self.pattern.split("...")]
        )

    __hash__ = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, str):
            return NotImplemented
        return bool(re.fullmatch(self.regex, other.strip(), re.DOTALL))

    def __repr__(self) -> str:
        return repr(self.pattern)


class WhitespaceInsensitive(str):
    __slots__ = ()

    def __hash__(self) -> int:
        return hash(re.sub(r"\s+", " ", self))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, str):
            return NotImplemented
        return re.sub(r"\s+", " ", self) == re.sub(r"\s+", " ", other)


class Approx:
    def __init__(
        self,
        value: float,
        rounding: float | odoo.addons.base.models.res_currency.ResCurrency,
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

    __hash__ = None


class TransactionCase(BaseCase):
    muted_registry_logger = mute_logger(odoo.orm.runtime.registry._logger.name)
    freeze_time = None

    @classmethod
    def _gc_filestore(cls) -> None:
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

        seed_planner_stats(cls.cr)

        cls.addClassCleanup(release_stranded_test_cursors, cls.__name__)

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
        envs = self.env.transaction.envs
        for env in list(envs):
            self.addCleanup(env.clear)
        self.addCleanup(envs.update, list(envs))
        self.addCleanup(envs.clear)

        self.addCleanup(self.muted_registry_logger(self.registry.clear_all_caches))

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

        self.env.flush_all()

        savepoint = Savepoint(self.cr)
        self.addCleanup(savepoint.close)

    @contextmanager
    def enter_registry_test_mode(self) -> Generator[None]:
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
        with ExitStack() as stack:
            if not type(self)._registry_patched:
                stack.enter_context(self.enter_registry_test_mode())
            yield


class SingleTransactionCase(BaseCase):
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
        seed_planner_stats(cls.cr)

        cls.env = api.Environment(cls.cr, api.SUPERUSER_ID, {})

    def setUp(self) -> None:
        super().setUp()
        self.env.flush_all()


def no_retry(arg: Any) -> Any:
    arg._retry = False
    return arg


def users(*logins: str) -> Callable:
    assert logins, "Expecting at least one login to execute"

    def users_decorator(func: Callable, /) -> Callable:
        @wraps(func)
        def with_users(self: Any, *args: Any, **kwargs: Any) -> None:
            old_uid = self.uid
            try:
                Users = self.env["res.users"].with_context(active_test=False)
                user_id = {
                    user.login: user.id
                    for user in Users.search([("login", "in", list(logins))])
                }
                missing = [login for login in logins if login not in user_id]
                assert not missing, f"No user with login {missing}"
                for login in logins:
                    with self.subTest(login=login):
                        self.uid = user_id[login]
                        func(self, *args, **kwargs)
                        self.env.flush_all()
                    self.env.invalidate_all()
            finally:
                self.uid = old_uid

        return with_users

    return users_decorator


def warmup(func: Callable, /) -> Callable:

    @wraps(func)
    def warmup(self: Any, *args: Any, **kwargs: Any) -> None:
        self.env.flush_all()
        self.env.invalidate_all()
        self.warm = False
        with contextlib.closing(self.cr.savepoint(flush=False)):
            func(self, *args, **kwargs)
            self.env.flush_all()
        self.env.invalidate_all()
        self.warm = True
        func(self, *args, **kwargs)

    return warmup


def can_import(module: str) -> bool:
    try:
        importlib.import_module(module)
    except ImportError:
        return False
    else:
        return True


def tagged(*tags: str) -> Callable:
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
        if isinstance(arg, type) and issubclass(arg, case.TestCase):
            arg.freeze_time = self
            return arg

        return self.freezer(arg)

    def __enter__(self) -> Any:
        return self.freezer.start()

    def __exit__(self, *args: object) -> None:
        self.freezer.stop()

    start = __enter__
    stop = __exit__


freezegun.freeze_time = freeze_time

# Imported at the bottom, after everything http.py needs from this module is
# defined. These names stay re-exported from `common` because addons and mock
# targets have always found them here.
from .http import (  # noqa: E402  http.py imports from this module; a top import would cycle
    HttpCase,
    JsonRpcException,
    Opener,
    Transport,
)
