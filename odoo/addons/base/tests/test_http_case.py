import logging
import threading
import time
from unittest.mock import Mock, patch

import requests
from werkzeug.exceptions import BadRequest

import odoo.http
from odoo.http import Controller, request, route
from odoo.tests.common import (
    TEST_CURSOR_COOKIE_NAME,
    ChromeBrowser,
    ChromeBrowserException,
    HttpCase,
    Like,
    tagged,
)
from odoo.tools import config

_logger = logging.getLogger(__name__)


@tagged("-at_install", "post_install")
class TestHttpCase(HttpCase):
    def test_console_error_string(self):
        with self.assertLogs(level="ERROR") as log_catcher:
            with self.assertRaises(AssertionError) as error_catcher:
                code = "console.error('test error','message')"
                with patch(
                    "odoo.tests.common.ChromeBrowser.take_screenshot",
                    return_value=None,
                ):
                    self.browser_js(url_path="about:blank", code=code)
            # last line must contain the error message
            self.assertEqual(
                error_catcher.exception.args[0].splitlines()[-1],
                "test error message",
            )
        self.assertEqual(len(log_catcher.output), 1)
        self.assertIn("test error message", log_catcher.output[0])

    def test_console_error_object(self):
        with self.assertLogs(level="ERROR") as log_catcher:
            with self.assertRaises(AssertionError) as error_catcher:
                code = "console.error(TypeError('test error message'))"
                with patch(
                    "odoo.tests.common.ChromeBrowser.take_screenshot",
                    return_value=None,
                ):
                    self.browser_js(url_path="about:blank", code=code)
            # last line must contain the error message
            self.assertEqual(
                error_catcher.exception.args[0].splitlines()[-2:],
                ["TypeError: test error message", "    at <anonymous>:1:15"],
            )
        self.assertEqual(len(log_catcher.output), 1)
        self.assertIn(
            "TypeError: test error message\n    at <anonymous>:1:15",
            log_catcher.output[0],
        )

    def test_console_log_object(self):
        logger = logging.getLogger("odoo")
        level = logger.level
        logger.setLevel(logging.INFO)
        self.addCleanup(logger.setLevel, level)

        with self.assertLogs() as log_catcher:
            code = "console.log({custom:{1:'test', 2:'a'}, value:1, description:'dummy'});console.log('test successful');"
            self.browser_js(url_path="about:blank", code=code)
        console_log_count = 0
        for log in log_catcher.output:
            if ".browser:" in log:
                text = log.split(".browser:", 1)[1]
                if text == "test successful":
                    continue
                if text.startswith("heap "):
                    continue
                self.assertEqual(
                    text, "Object(custom=Object, value=1, description='dummy')"
                )
                console_log_count += 1
        self.assertEqual(console_log_count, 1)


@tagged("-at_install", "post_install")
class TestRunbotLog(HttpCase):
    def test_runbot_js_log(self):
        """Test that a ChromeBrowser console.dir is handled server side as a log of level RUNBOT."""
        log_message = "this is a small test"
        with self.assertLogs() as log_catcher:
            self.browser_js(
                "about:blank",
                f"console.runbot = console.dir; console.runbot('{log_message}'); console.log('test successful');",
            )
        found = False
        for record in log_catcher.records:
            if record.message == log_message:
                self.assertEqual(record.levelno, logging.RUNBOT)
                self.assertTrue(record.name.endswith("browser"))
                found = True
        self.assertTrue(found, "Runbot log not found")


@tagged("-at_install", "post_install")
class TestAllowRequests(HttpCase):
    def test_allow_all_requests_flag_scoped(self):
        """all_requests=True must not outlive its context: a leaked flag
        silently disables the stale-request cookie protection for the rest
        of the test."""
        self.assertFalse(self.http_request_allow_all)
        with self.allow_requests(all_requests=True):
            self.assertTrue(self.http_request_allow_all)
        self.assertFalse(self.http_request_allow_all)

    def test_allow_all_requests_flag_restored_after_xmlrpc(self):
        """Transport passes all_requests=True; the flag used to leak."""
        self.assertFalse(self.http_request_allow_all)
        self.xmlrpc_common.version()
        self.assertFalse(self.http_request_allow_all)

    def test_cookieless_request_refused_after_xmlrpc(self):
        """End to end: a request without the test-cursor cookie must still be
        refused (400) after an XML-RPC call earlier in the same test."""
        self.xmlrpc_common.version()
        with self.allow_requests():
            response = requests.get(
                self.base_url() + "/odoo/tests/no/such/route",
                timeout=30,
                allow_redirects=False,
            )
        self.assertEqual(response.status_code, 400)

    def test_cookie_guard_unit(self):
        """assertCanOpenTestCursor: cookie-less request -> BadRequest, unless
        the allow-all flag is up."""
        fake_request = Mock(cookies={}, httprequest=Mock(path="/probe"))
        with patch.object(odoo.http, "request", fake_request):
            with self.assertRaises(BadRequest):
                self.assertCanOpenTestCursor()
            with patch.object(self, "http_request_allow_all", True):
                self.assertCanOpenTestCursor()  # must not raise


@tagged("-at_install", "post_install")
class TestChromeBrowser(HttpCase):
    def setUp(self):
        super().setUp()
        screencasts_dir = config["screencasts"] or config["screenshots"]
        with patch.dict(
            config.options,
            {
                "screencasts": screencasts_dir,
                "screenshots": config["screenshots"],
            },
        ):
            self.browser = ChromeBrowser(self)
        self.addCleanup(self.browser.stop)

    def test_screencasts(self):
        self.browser.screencaster.start()
        self.browser.navigate_to("about:blank")
        self.browser._wait_ready()
        code = "setTimeout(() => console.log('test successful'), 2000); setInterval(() => document.body.innerText = (new Date()).getTime(), 100);"
        self.browser._wait_code_ok(code, 10)
        self.browser.screencaster.save()

    def test_wait_ready_pending_promise_returns_false(self):
        """A never-resolving ready promise must yield False within the
        budget — the evaluate-phase TimeoutError must not escape (bool
        contract)."""
        self.browser.navigate_to("about:blank")
        self.browser._wait_ready()
        start = time.monotonic()
        with patch.object(ChromeBrowser, "take_screenshot", return_value=None):
            ok = self.browser._wait_ready("new Promise(() => {})", timeout=1)
        self.assertFalse(ok)
        self.assertLess(time.monotonic() - start, 10)

    def test_wait_ready_throttling_applied_once(self):
        """The wall-clock budget is timeout*factor — the factor used to be
        applied a second time inside _websocket_request (factor squared)."""
        self.browser.navigate_to("about:blank")
        self.browser._wait_ready()
        self.browser.throttling_factor = 3  # budgets only; Chrome untouched
        try:
            start = time.monotonic()
            with patch.object(ChromeBrowser, "take_screenshot", return_value=None):
                ok = self.browser._wait_ready("new Promise(() => {})", timeout=1)
            elapsed = time.monotonic() - start
        finally:
            self.browser.throttling_factor = 1
        self.assertFalse(ok)
        self.assertGreater(elapsed, 2.5)  # single application: ~3s
        self.assertLess(elapsed, 7)  # squared application was ~9s

    def test_wait_code_ok_wraps_evaluate_timeout(self):
        """Code whose promise outlives the budget must raise
        ChromeBrowserException (screenshot taken), not a bare TimeoutError
        that bypasses browser_js's error handling."""
        self.browser.navigate_to("about:blank")
        self.browser._wait_ready()
        with patch.object(ChromeBrowser, "take_screenshot", return_value=None):
            with self.assertRaises(ChromeBrowserException):
                self.browser._wait_code_ok("new Promise(() => {})", timeout=1)

    def test_wait_code_ok_budget_not_extended(self):
        """The post-evaluate wait consumes the *remaining* budget: evaluate
        eats ~2s of a 3s budget, so the call must fail ~3s in — the flipped
        formula used to grant elapsed+timeout more (~7s total)."""
        self.browser.navigate_to("about:blank")
        self.browser._wait_ready()
        start = time.monotonic()
        with patch.object(ChromeBrowser, "take_screenshot", return_value=None):
            with self.assertRaises(ChromeBrowserException):
                self.browser._wait_code_ok(
                    "new Promise(r => setTimeout(r, 2000))", timeout=3
                )
        elapsed = time.monotonic() - start
        self.assertGreater(elapsed, 2.5)
        self.assertLess(elapsed, 5.5)


@tagged("-at_install", "post_install")
class TestChromeBrowserOddDimensions(TestChromeBrowser):
    allow_inherited_tests_method = True
    browser_size = "1215x768"


class TestRequestRemainingCommon(HttpCase):
    # Reproduces a request lost between two tests and executed during the next:
    # - test A's browser js finishes with a pending request
    # - _wait_remaining_requests misses it (thread not yet spawned/named)
    # - test B starts and executes a SELECT
    # - the request runs a concurrent fetchall, so B's fetchall fails on the
    #   already-used cursor
    # Similar cases can also consume savepoints, make the main cursor readonly, ...

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.thread_a = None
        # this lock is used to ensure the request is executed after test b starts
        cls.main_lock = threading.Lock()
        cls.main_lock.acquire()

        class Dummycontroller(Controller):
            @route("/web/concurrent", type="http", auth="public", sitemap=False)
            def wait(self, **params):
                assert request.env.cr.__class__.__name__ == "TestCursor"
                request.env.cr.execute("SELECT 1")
                request.env.cr.fetchall()
                # note that the previous queries are not really needed since the http stack will check the registry
                # but this makes the test more clear and robust
                _logger.info("B finish")

        cls.env.registry.clear_cache("routing")
        cls.addClassCleanup(cls.env.registry.clear_cache, "routing")

    def _test_requests_a(self, cookie=False):

        def late_request_thread():
            # In some rare case the request may arrive after _wait_remaining_requests.
            # this thread is trying to reproduce this case.
            _logger.info("Waiting for B to start")
            if self.main_lock.acquire(timeout=10):
                _logger.info("Opening url")
                # don't use url_open since it simulates a lost request from chrome and url_open would wait to acquire the lock
                s = requests.Session()
                if cookie:
                    s.cookies.set(TEST_CURSOR_COOKIE_NAME, self.canonical_tag)
                s.get(self.base_url() + "/web/concurrent", timeout=10)
            else:
                _logger.error(
                    "Something went wrong and thread was not able to aquire lock"
                )

        type(self).thread_a = threading.Thread(target=late_request_thread)
        self.thread_a.start()

    def _test_requests_b(self):
        self.env.cr.execute("SELECT 1")
        self.main_lock.release()
        _logger.info("B started, waiting for A to finish")
        self.thread_a.join()
        self.env.cr.fetchall()


class TestRequestRemainingNoCookie(TestRequestRemainingCommon):
    def test_requests_a(self):
        self._test_requests_a()

    def test_requests_b(self):
        with self.assertLogs("odoo.tests.common") as log_catcher:
            self._test_requests_b()
        self.assertEqual(
            log_catcher.output,
            [
                Like(
                    "... odoo.tests.common:Request with path /web/concurrent has been ignored during test as it does not contain the test_cursor cookie or it is expired. "
                    '(required "None (request are not enabled)", got "None")'
                )
            ],
        )


class TestRequestRemainingNotEnabled(TestRequestRemainingCommon):
    def test_requests_a(self):
        self._test_requests_a(cookie=True)

    def test_requests_b(self):
        with self.assertLogs("odoo.tests.common") as log_catcher:
            self._test_requests_b()
        self.assertEqual(
            log_catcher.output,
            [
                Like(
                    "... odoo.tests.common:Request with path /web/concurrent has been ignored during test as it does not contain the test_cursor cookie or it is expired. "
                    '(required "None (request are not enabled)", got "/base/tests/test_http_case.py:TestRequestRemainingNotEnabled.test_requests_a")'
                )
            ],
        )


class TestRequestRemainingStartDuringNext(TestRequestRemainingCommon):
    def test_requests_a(self):
        self._test_requests_a(cookie=True)

    def test_requests_b(self):
        with (
            self.assertLogs("odoo.tests.common") as log_catcher,
            self.allow_requests(),
        ):
            self._test_requests_b()
        self.assertEqual(
            log_catcher.output,
            [
                Like(
                    "... odoo.tests.common:Request with path /web/concurrent has been ignored during test as it does not contain the test_cursor cookie or it is expired. "
                    '(required "/base/tests/test_http_case.py:TestRequestRemainingStartDuringNext.test_requests_b__0", got "/base/tests/test_http_case.py:TestRequestRemainingStartDuringNext.test_requests_a")'
                )
            ],
        )


class TestRequestRemainingAfterFirstCheck(TestRequestRemainingCommon):
    """Implementation-specific: the lock is acquired after the next thread.

    - test_requests_a closes browser js, acquires the lock
    - a ghost request opens a test cursor, makes the first check
      (assertCanOpenTestCursor)
    - the next test enables requests (url_open), releasing the lock
    - the pending request runs but detects the test change
    """

    def test_requests_a(self, cookie=False):
        self.http_request_key = self.canonical_tag

        def late_request_thread():
            _logger.info("Opening url")
            # don't use url_open since it simulates a lost request from chrome and url_open would wait to acquire the lock
            s = requests.Session()
            s.cookies.set(TEST_CURSOR_COOKIE_NAME, self.http_request_key)
            # we expect the request to be stuck when acquiring the registry lock
            s.get(self.base_url() + "/web/concurrent", timeout=10)

        type(self).thread_a = threading.Thread(target=late_request_thread)
        main_lock = self.main_lock
        self.thread_a.start()
        # we need to ensure that the first check is made and that we are acquiring the lock
        main_lock.acquire()

    def assertCanOpenTestCursor(self):
        super().assertCanOpenTestCursor()
        # the first time we check assertCanOpenTestCursor we need to release the lock (locks ensure we are still inside test_requests_a)
        if self.main_lock:
            self.main_lock.release()
            self.main_lock = None

    def test_requests_b(self):
        _logger.info("B started, waiting for A to finish")
        # url_open will simulate an enabled request
        with (
            self.assertLogs("odoo.tests.common") as log_catcher,
            self.allow_requests(),
        ):
            self.thread_a.join()
        self.assertEqual(
            log_catcher.output,
            [
                Like(
                    "... Trying to open a test cursor for /base/tests/test_http_case.py:TestRequestRemainingAfterFirstCheck.test_requests_a while already in a test /base/tests/test_http_case.py:TestRequestRemainingAfterFirstCheck.test_requests_b"
                )
            ],
        )
