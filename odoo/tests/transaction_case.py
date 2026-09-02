import contextlib
import difflib
import inspect
import logging
import pathlib
import pprint
import re
import sys
import threading
import traceback
import warnings
from collections import deque
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import date, datetime
from itertools import zip_longest
from typing import TYPE_CHECKING, Any, ClassVar, cast
from unittest import TestResult
from unittest.mock import Mock, _patch, patch
from urllib.parse import urlsplit

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
from odoo.libs.password import CryptContext
from odoo.logutils import RUNBOT
from odoo.modules.registry import DummyRLock, Registry
from odoo.tools import (
    SQL,
    DotDict,
    mute_logger,
    profiler,
)
from odoo.tools.misc import lower_logging

from .case import TestCase
from .cursor import TestCursor
from .matchers import Approx, _normalize_arch_for_assert
from .utils import HOST, env_int, get_db_name

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable

    from .result import OdooTestResult


_logger = logging.getLogger(__name__)


TEST_CURSOR_COOKIE_NAME = "test_request_key"


class RegistryRLock(threading._RLock):  # type: ignore[misc]  # only the private class is subclassable
    @property
    def count(self) -> int:
        return self._count


_registry_test_lock = RegistryRLock()


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


def _has_child_processes() -> bool:
    try:
        return any(
            (task / "children").read_text().strip()
            for task in pathlib.Path("/proc/self/task").iterdir()
        )
    except OSError:
        return True


def gc_test_filestore() -> None:
    try:
        with Registry(get_db_name()).cursor() as cr:
            gc_env = api.Environment(cr, api.SUPERUSER_ID, {})
            gc_env["ir.attachment"]._gc_file_store_unsafe()
    except Exception:
        _logger.warning("Could not sweep the filestore after the suite", exc_info=True)


def release_stranded_test_cursors(owner: str = "") -> int:
    stranded = TestCursor._cursors_stack
    for cursor in reversed(stranded):
        _logger.warning(
            "A cursor was remaining in the TestCursor stack at the end of %s; "
            "releasing its registry lock",
            owner or "the test",
        )
        try:
            cursor._close_savepoint(rollback=True)
        except Exception:
            _logger.warning(
                "Could not roll back the savepoint of the cursor stranded by %s",
                owner or "the test",
                exc_info=True,
            )
        cursor._closed = True
        cursor._lock.release()
    count = len(stranded)
    TestCursor._cursors_stack = []
    return count


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


def _normalise_expected(
    records: odoo.models.BaseModel,
    expected_values: list[dict],
    field_names: Iterable[str],
) -> list[dict]:
    rows = []
    for vs in expected_values:
        row: dict[str, Any] = {}
        for name in field_names:
            field_type = records._fields[name].type
            if vs[name] is None:
                row[name] = False
            elif field_type in ("one2many", "many2many"):
                row[name] = sorted(vs[name])
            elif field_type == "float":
                row[name] = float(vs[name])
            elif field_type == "integer":
                row[name] = int(vs[name])
            else:
                row[name] = vs[name]
        rows.append(row)
    return rows


def _normalise_records(
    records: odoo.models.BaseModel, field_names: Iterable[str]
) -> list[dict]:
    rows = []
    for record in records:
        row: dict[str, Any] = {}
        for field_name in field_names:
            record_value = record[field_name]
            match record._fields[field_name]:
                case odoo.fields.Many2one():
                    record_value = record_value.id
                case odoo.fields.One2many() | odoo.fields.Many2many():
                    record_value = sorted(record_value.ids)
                case odoo.fields.Float() as field if isinstance(
                    digits := field.get_digits(record.env), tuple
                ):
                    record_value = Approx(record_value, digits[1], decorate=False)
                case odoo.fields.Monetary() as field if (
                    currency_field_name := field.get_currency_field(record)
                ):
                    if c := record[currency_field_name]:
                        record_value = Approx(record_value, c, decorate=False)

            row[field_name] = record_value
        rows.append(row)
    return rows


class BaseCase(TestCase):
    registry: Registry = None  # type: ignore[assignment]
    env: api.Environment = None  # type: ignore[assignment]
    cr: Cursor = None  # type: ignore[assignment]
    registry_patches: ClassVar[list]

    test_tags: set[str] | None = None
    freeze_time: ClassVar[Any] = None
    _starts_freeze_time_itself = False

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
            test_method = getattr(self, methodName)
            test_tags = (self.test_tags or set()) | set(
                self.get_method_additional_tags(test_method)
            )
            test_tags |= getattr(test_method, "test_tags", set())
            test_tags -= getattr(test_method, "test_tags_exclude", set())
            self.test_tags = test_tags

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

    def run(self, result: OdooTestResult) -> None:  # type: ignore[override]  # a result is mandatory here
        testMethod = getattr(self, self._testMethodName)

        if getattr(testMethod, "_retry", True) and getattr(self, "_retry", True):
            tests_run_count = self._tests_run_count
        else:
            tests_run_count = 1
            _logger.info("Auto retry disabled for %s", self)

        for retry in range(tests_run_count):
            result.had_failure = False
            if retry:
                _logger.log(RUNBOT, "Retrying a failed test: %s", self)
            with ExitStack() as attempt:
                if retry:
                    attempt.enter_context(result.retry())

                if retry == tests_run_count - 1:
                    super().run(cast("TestResult", result))
                    if not result.wasSuccessful() and BaseCase._tests_run_count != 1:
                        _logger.log(RUNBOT, "Disabling auto-retry after a failed test")
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
            if not _has_child_processes():
                return
            current_process = psutil.Process()
            children = current_process.children(recursive=True)
            for child in children:
                _logger.warning("A child process was found, terminating it: %s", child)
                child.terminate()
            _, alive = psutil.wait_procs(children, timeout=10)
            if alive:
                _logger.warning(
                    "Killing %d child process(es) that survived terminate(): %s",
                    len(alive),
                    ", ".join(str(p) for p in alive),
                )
                for child in alive:
                    child.kill()
                psutil.wait_procs(alive, timeout=5)

        cls.addClassCleanup(check_remaining_processes)

        def check_remaining_patchers():
            for patcher in list(_patch._active_patches):  # type: ignore[attr-defined]  # mock keeps the registry private
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
        if cls.freeze_time and not cls._starts_freeze_time_itself:
            cls.startClassPatcher(cls.freeze_time)
        class_tags = cls.test_tags or set()
        if "standard" in class_tags or "click_all" in class_tags:
            patcher = patch.object(
                requests.sessions.Session,
                "send",
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
        return cast("Cursor", self.registry.cursor())

    @classmethod
    def _open_class_cursor(cls) -> None:
        cls.cr = cast("Cursor", cls.registry.cursor())
        cls.addClassCleanup(cls.cr.close)
        seed_planner_stats(cls.cr)

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
            session=DotDict(odoo.http.prepare_default_session(), debug="1"),
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

    def assertRaises(  # type: ignore[override]  # narrowed to one exception type
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
        actual_queries: list[str] = []

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
        actual_queries: list[str] = []

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
    def capturedQueries(self, flush: bool = True) -> Generator[list[str]]:
        yield from self._patchExecute([], flush)

    @contextmanager
    def assertQueryCount(
        self, default: int = 0, flush: bool = True, **counters: int
    ) -> Generator[None]:
        if self.warm:
            with patch("random.random", lambda: 1):
                login = self.env.user.login  # type: ignore[attr-defined]  # res.users is an addon model
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
            if not expected_values:
                self.assertFalse(
                    records,
                    f"expected no record, got {len(records)}: {records}",
                )
                return
            field_names = expected_values[0].keys()
            for i, v in enumerate(expected_values):
                self.assertEqual(
                    v.keys(),
                    field_names,
                    f"All expected values must have the same keys, found differences between records 0 and {i}",
                )

        expected_reformatted = _normalise_expected(
            records, expected_values, field_names
        )
        record_reformatted = _normalise_records(records, field_names)

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

    _DEPENDS_PROBE_VALUES: ClassVar[dict[str, list[Any]]] = {
        "char": ["zzz-probe"],
        "text": ["zzz-probe"],
        "html": ["<p>zzz-probe</p>"],
        "boolean": [True, False],
        "integer": [7],
        "float": [3.5],
        "monetary": [3.5],
        "date": [date(2021, 3, 4)],
        "datetime": [datetime(2021, 3, 4, 5, 6, 7)],
    }

    _DEPENDS_PROBE_DYNAMIC = frozenset({"selection", "many2one"})

    def assertDependsComplete(
        self,
        records: odoo.models.BaseModel,
        *,
        probe_fields: Iterable[str] | None = None,
        computed_fields: Iterable[str] | None = None,
        known_incomplete: Iterable[str] | None = None,
        msg: str | None = None,
    ) -> None:
        self.assertTrue(records, msg or "assertDependsComplete needs records")
        model = records.browse(records.ids)
        exempt = set(known_incomplete or ())
        if unknown := exempt - set(
            self._depends_computed_names(model, computed_fields)
        ):
            self.fail(
                f"known_incomplete names {sorted(unknown)}, which are not "
                f"computed fields of {model._name}"
            )
        stale = self.findStaleComputedFields(
            records, probe_fields=probe_fields, computed_fields=computed_fields
        )
        if unproven := exempt - {entry[1] for entry in stale}:
            self.fail(
                f"known_incomplete names {sorted(unproven)} on {model._name}, "
                f"but nothing made them stale. Either the dependency is now "
                f"expressible and should be declared, or drop them from the list."
            )
        if reportable := [entry for entry in stale if entry[1] not in exempt]:
            self.fail(msg or self._depends_failure_message(model, reportable))

    @staticmethod
    def _depends_computed_names(
        model: odoo.models.BaseModel, computed_fields: Iterable[str] | None
    ) -> list[str]:
        if computed_fields is not None:
            return list(computed_fields)
        return [
            name
            for name, f in model._fields.items()
            if f.compute and not f.related and name != "id"
        ]

    def _depends_probe_names(
        self, model: odoo.models.BaseModel, probe_fields: Iterable[str] | None
    ) -> list[str]:
        if probe_fields is not None:
            return list(probe_fields)
        fields = model._fields
        probes = [
            name
            for name, f in fields.items()
            if f.store
            and not (f.readonly or f.compute or f.related)
            and (
                f.type in self._DEPENDS_PROBE_VALUES
                or f.type in self._DEPENDS_PROBE_DYNAMIC
            )
        ]
        probes.sort(key=lambda name: fields[name].type == "many2one")
        return probes

    def findStaleComputedFields(
        self,
        records: odoo.models.BaseModel,
        *,
        probe_fields: Iterable[str] | None = None,
        computed_fields: Iterable[str] | None = None,
    ) -> list[tuple[str, str, Any, Any, Any]]:
        model = records.browse(records.ids)
        fields = model._fields
        computed = self._depends_computed_names(model, computed_fields)
        return [
            entry
            for name in self._depends_probe_names(model, probe_fields)
            for value in self._depends_probe_values(model, fields[name])
            for entry in self._depends_probe(model, computed, name, value)
        ]

    def _depends_probe_values(
        self, records: odoo.models.BaseModel, field: Any
    ) -> list[Any]:
        if field.type == "many2one":
            return self._depends_probe_comodel_ids(records, field)
        if field.type in self._DEPENDS_PROBE_DYNAMIC:
            with contextlib.suppress(Exception):
                return list(field.get_values(records.env))[:2]
            return []
        return self._DEPENDS_PROBE_VALUES.get(field.type, [])

    @staticmethod
    def _depends_probe_comodel_ids(
        records: odoo.models.BaseModel, field: Any
    ) -> list[Any]:
        try:
            comodel = records.env[field.comodel_name].sudo()
            held = {record[field.name].id for record in records} - {False}
            candidate = comodel.with_context(active_test=False).search(
                [("id", "not in", list(held))], limit=1
            )
        except Exception:
            return []
        return candidate.ids

    def _depends_probe(
        self,
        records: odoo.models.BaseModel,
        computed: list[str],
        probe_name: str,
        value: Any,
    ) -> list[tuple[str, str, Any, Any, Any]]:
        env = records.env
        savepoint = env.cr.savepoint(flush=False)
        try:
            env.flush_all()
            env.invalidate_all()
            target = records[0]
            current = target[probe_name]
            if isinstance(current, odoo.models.BaseModel):
                if current.id == value:
                    return []
            elif current == value:
                return []
            if self._depends_forced_recompute(records, computed) is None:
                return []
            env.invalidate_all()
            before = self._depends_read(records, computed)
            target.write({probe_name: value})
            cached = self._depends_read(records, computed)
            env.flush_all()
            env.invalidate_all()
            fresh = self._depends_read(records.browse(records.ids), computed)
            if before is None or cached is None or fresh is None:
                return []
            recomputed = self._depends_forced_recompute(records, computed)
            if recomputed is None:
                return []
            fresh = {**fresh, **recomputed}
        except Exception:
            return []
        finally:
            savepoint.rollback()
            savepoint.close(rollback=False)
            env.clear()
        stale = []
        for key in before:
            if key not in cached or key not in fresh:
                continue
            if cached[key] != fresh[key]:
                stale.append((probe_name, key[1], value, cached[key], fresh[key]))
        return stale

    def _depends_forced_recompute(
        self, records: odoo.models.BaseModel, field_names: list[str]
    ) -> dict[tuple[Any, str], Any] | None:
        stored = [
            name
            for name in field_names
            if (field := records._fields.get(name)) is not None
            and field.store
            and field.compute
            and field.readonly
        ]
        if not stored:
            return {}
        env = records.env
        try:
            for name in stored:
                env.add_to_compute(records._fields[name], records)
            env.flush_all()
            env.invalidate_all()
            return self._depends_read(records.browse(records.ids), stored)
        except Exception:
            return None

    @staticmethod
    def _depends_read(
        records: odoo.models.BaseModel, field_names: list[str]
    ) -> dict[tuple[Any, str], Any] | None:
        values: dict[tuple[Any, str], Any] = {}
        for record in records:
            for name in field_names:
                try:
                    value = record[name]
                except Exception:
                    return None
                values[record.id, name] = (
                    tuple(value._ids)
                    if isinstance(value, odoo.models.BaseModel)
                    else value
                )
        return values

    @staticmethod
    def _depends_failure_message(
        records: odoo.models.BaseModel, stale: list[tuple[str, str, Any, Any, Any]]
    ) -> str:
        depends = records.env.registry.field_depends
        lines = [
            (
                f"{len(stale)} computed field(s) on {records._name} went stale "
                f"after a write to a field they do not depend on:"
            )
        ]
        seen: set[tuple[str, str]] = set()
        for probe_name, name, value, cached, fresh in stale:
            if (probe_name, name) in seen:
                continue
            seen.add((probe_name, name))
            declared = sorted(set(depends.get(records._fields[name], ())))
            lines.append(
                f"  {records._name}.{name} after writing {probe_name}={value!r}\n"
                f"      cached  {cached!r}\n"
                f"      fresh   {fresh!r}\n"
                f"      depends {declared}"
            )
        return "\n".join(lines)

    def assertSweep(self, candidates: Any, msg: str | None = None) -> list:
        found = list(candidates)
        self.assertTrue(
            found,
            msg or "the sweep found nothing to check, so it proves nothing",
        )
        return found

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
            self.profile_session = profiler.get_session_name(test_method)
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
                cast("Any", _registry_test_lock),
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
            _logger.log(RUNBOT, message)
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
            _logger.log(
                RUNBOT,
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
            return []
        return [tag for tag, needle in wanted.items() if needle in method_source]


class TransactionCase(BaseCase):
    muted_registry_logger = mute_logger(odoo.orm.runtime.registry._logger.name)
    registry_start_invalidated: ClassVar[bool]
    registry_start_sequence: ClassVar[int]
    registry_cache_sequences: ClassVar[dict]
    _signal_changes_patcher: ClassVar[Any]
    commit_patcher: ClassVar[Any]
    rollback_patcher: ClassVar[Any]
    close_patcher: ClassVar[Any]
    _crypt_context_patcher: ClassVar[Any]
    _starts_freeze_time_itself = True

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
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

        cls._open_class_cursor()

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
        cls.env.transaction.default_env = cls.env

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
    _starts_freeze_time_itself = True

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

        cls._open_class_cursor()

        if cls.freeze_time:
            cls.startClassPatcher(cls.freeze_time)

        cls.env = api.Environment(cls.cr, api.SUPERUSER_ID, {})
        cls.env.transaction.default_env = cls.env

    def setUp(self) -> None:
        super().setUp()
        self.env.flush_all()
