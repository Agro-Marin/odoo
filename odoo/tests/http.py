"""HTTP test-case layer: :class:`HttpCase` and its request plumbing.

Extracted from :mod:`odoo.tests.common` (like the Chrome CDP client in
:mod:`odoo.tests.browser` before it).  ``HttpCase``, ``Opener``,
``Transport`` and ``JsonRpcException`` remain re-exported from
``odoo.tests.common`` for compatibility, including as mock/patch targets —
in particular ``browser_js`` instantiates ``ChromeBrowser`` through
``common``'s module globals so ``patch("odoo.tests.common.ChromeBrowser")``
keeps working.
"""

import base64
import contextlib
import inspect
import itertools
import json
import logging
import threading
import time
import unittest
from contextlib import ExitStack, contextmanager
from typing import TYPE_CHECKING, Any
from unittest.mock import patch
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from uuid import uuid4
from xmlrpc import client as xmlrpclib

import requests

import odoo.http
from odoo import api
from odoo.service import security
from odoo.tools import profiler

from . import common
from .browser import DEFAULT_SUCCESS_SIGNAL, ChromeBrowser, ChromeBrowserException
from .common import (
    TEST_CURSOR_COOKIE_NAME,
    TransactionCase,
    release_test_lock,
)
from .utils import HOST, env_int, get_db_name

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

_logger = logging.getLogger(__name__)


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
        if cls.http_port() is None:
            # base_url() would otherwise die formatting None as %d — an
            # opaque TypeError deep in setUpClass when the server runs
            # without a listening httpd (--no-http, misconfigured preload).
            raise unittest.SkipTest(
                f"{cls.__name__} requires a running HTTP server (--no-http?)"
            )
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
        # A server object can exist without a listening ``httpd`` (--no-http,
        # ``odoo shell``, a server still starting up). Callers rely on the
        # documented ``None`` -- e.g. http_routing's ``MockRequest`` does
        # ``if HttpCase.http_port():`` -- so answer None there too instead of
        # raising AttributeError on the missing attribute.
        httpd = getattr(odoo.service.lifecycle.server, "httpd", None)
        return httpd.server_port if httpd is not None else None

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
        # ServerProxy("close") returns the proxy's close method (stdlib API)
        for proxy in (self.xmlrpc_common, self.xmlrpc_db, self.xmlrpc_object):
            self.addCleanup(proxy("close"))
        # setup an url opener helper
        self.opener = Opener(self)
        # close whichever Opener is current at teardown (authenticate()
        # replaces it); otherwise sockets linger until garbage collection
        self.addCleanup(lambda: self.opener.close())  # noqa: PLW0108  # late-bound: authenticate() may replace self.opener
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
                # patch.object so the flag is restored on exit: a plain
                # assignment leaked `True` for the rest of the test, silently
                # disabling the stale-request cookie protection below after
                # the first XML-RPC call (Transport passes all_requests=True).
                defer.enter_context(patch.object(self, "http_request_allow_all", True))
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
        self.opener.close()  # the replaced session would only be GC-reclaimed
        self.opener = Opener(self)
        self.opener.cookies.set("session_id", session.sid, domain=HOST)
        if browser:
            self._logger.info("Setting session cookie in browser")
            # http_only mirrors the server's httponly session_id cookie; JS never
            # reads it, and leaving it JS-visible would pollute HOOT's MockCookie jar.
            browser.set_cookie("session_id", session.sid, "/", HOST, http_only=True)

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

        # instantiate through common's module globals: bus/web tests patch
        # "odoo.tests.common.ChromeBrowser" and must keep affecting us
        browser = common.ChromeBrowser(
            self, headless=not watch, success_signal=success_signal, debug=debug
        )
        with contextlib.ExitStack() as atexit:
            # safety net registered first (thus run last): guarantees Chrome is
            # stopped and its profile dir removed even when the setup below
            # (authenticate, cookies, navigate) fails before the happy-path
            # browser.stop registration; stop() is idempotent
            atexit.callback(browser.stop)
            atexit.enter_context(self.allow_requests(browser=browser))
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

            # used by dedicated runbot builds
            cpu_throttling_os = env_int("ODOO_BROWSER_CPU_THROTTLING", 0)
            cpu_throttling = cpu_throttling_os or cpu_throttling

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
                env_int("ODOO_TOUR_DELAY_TO_CHECK_UNDETERMINISMS", 0),
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
            json=self.build_rpc_payload(params),
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
