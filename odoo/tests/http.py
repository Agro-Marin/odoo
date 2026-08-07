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
    def __init__(self, http_case: HttpCase) -> None:
        super().__init__()
        self.test_case = http_case
        self.cr = http_case.cr

    def request(self, *args: Any, **kwargs: Any) -> Any:
        assert self.test_case.opener == self
        self.cr.flush()
        self.cr.clear()
        with self.test_case.allow_requests():
            return super().request(*args, **kwargs)


class Transport(xmlrpclib.Transport):
    def __init__(self, http_case: HttpCase) -> None:
        self.test_case = http_case
        self.cr = http_case.cr
        super().__init__()

    def request(self, *args: Any, **kwargs: Any) -> Any:
        self.cr.flush()
        self.cr.clear()
        with self.test_case.allow_requests(all_requests=True):
            return super().request(*args, **kwargs)


class JsonRpcException(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


class HttpCase(TransactionCase):
    registry_test_mode = True
    browser = None
    browser_size = "1366x768"
    touch_enabled = False
    session: odoo.http.Session = None

    _logger: logging.Logger = None

    @classmethod
    def setUpClass(cls) -> None:
        if cls.http_port() is None:
            raise unittest.SkipTest(
                f"{cls.__name__} requires a running HTTP server (--no-http?)"
            )
        super().setUpClass()
        if cls.registry_test_mode:
            cls.registry_enter_test_mode_cls()

        ICP = cls.env["ir.config_parameter"]
        ICP.set_param("web.base.url", cls.base_url())
        ICP.env.flush_all()
        cls.xmlrpc_url = f"{cls.base_url()}/xmlrpc/2/"
        cls._logger = logging.getLogger("%s.%s" % (cls.__module__, cls.__name__))

    @classmethod
    def base_url(cls) -> str:
        return f"http://{HOST}:{cls.http_port():d}"

    @classmethod
    def http_port(cls) -> int | None:
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
        for proxy in (self.xmlrpc_common, self.xmlrpc_db, self.xmlrpc_object):
            self.addCleanup(proxy("close"))
        self.opener = Opener(self)
        self.addCleanup(self.opener.close)
        self.http_key_sequence = itertools.count()

    @contextmanager
    def enter_registry_test_mode(self) -> Generator[None]:
        _logger.warning("HTTPCase is already in test mode")
        yield

    @contextmanager
    def allow_pdf_render(self) -> Generator[None]:
        _logger.warning("HTTPCase does not require calling allow_pdf_render")
        yield

    @contextmanager
    def allow_requests(self, browser: ChromeBrowser | None = None, all_requests=False):
        with ExitStack() as defer:
            defer.enter_context(release_test_lock())
            if all_requests:
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
                browser.set_cookie(
                    TEST_CURSOR_COOKIE_NAME,
                    self.http_request_key,
                    "/",
                    HOST,
                    http_only=True,
                )
            yield

    def parse_http_location(self, location: str | None) -> Any:
        if not location:
            return urlsplit("")
        s = urlsplit(urljoin(self.base_url(), location))
        return s._replace(query=urlencode(parse_qsl(s.query)))

    def assertURLEqual(
        self, test_url: str, truth_url: str, message: str | None = None
    ) -> None:
        self.assertEqual(
            self.parse_http_location(test_url),
            self.parse_http_location(truth_url),
            message,
        )

    def build_rpc_payload(self, params: dict | None = None) -> dict:
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
            _trace_disable=True,
        )
        session.context["lang"] = odoo.http.DEFAULT_LANG

        if session_extra:
            if extra_ctx := session_extra.pop("context", None):
                session.context.update(extra_ctx)
            session.update(session_extra)

        if user:
            self.cr.flush()
            self.cr.clear()

            def patched_check_credentials(self, credential, env):
                return {
                    "uid": self.id,
                    "auth_method": "password",
                    "mfa": "default",
                }

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
        old_opener = getattr(self, "opener", None)
        if old_opener is not None:
            old_opener.close()
        self.opener = Opener(self)
        self.opener.cookies.set("session_id", session.sid, domain=HOST)
        if browser:
            self._logger.info("Setting session cookie in browser")
            browser.set_cookie("session_id", session.sid, "/", HOST, http_only=True)

        return session

    def fetch_proxy(self, url: str) -> dict:

        if "https://fonts.googleapis.com/css" in url:
            _logger.info(
                "External chrome request during tests: Return empty file for %s",
                url,
            )
            return self.make_fetch_proxy_response("")

        _logger.info("External chrome request during tests: returning 404 for %s", url)
        return {
            "body": "",
            "responseCode": 404,
            "responseHeaders": [],
        }

    def make_fetch_proxy_response(self, content: str | bytes, code: int = 200) -> dict:
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
        if not self.env.registry.loaded:
            self._logger.warning("HttpCase test should be in post_install only")

        if any(
            f.filename.endswith("/coverage/execfile.py")
            for f in inspect.stack()
            if f.filename
        ):
            timeout *= 1.5

        if debug is not False:
            watch = True
            timeout = 1e6
        if watch:
            self._logger.warning("watch mode is only suitable for local testing")

        browser = common.ChromeBrowser(
            self, headless=not watch, success_signal=success_signal, debug=debug
        )
        with contextlib.ExitStack() as atexit:
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
                    self.env.cr.precommit.run()
                    self.env.cr.postcommit.run()

                atexit.enter_context(patch.object(BusBus, "_sendone", sendone_wrapper))
                atexit.enter_context(
                    patch.object(
                        WebsocketConnectionHandler,
                        "websocket_allowed",
                        return_value=True,
                    )
                )

            self.authenticate(login, login, browser=browser)
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

            self.assertTrue(
                browser._wait_ready(ready),
                'The ready "%s" code was always falsy' % ready,
            )

            error = False
            try:
                browser._wait_code_ok(code, timeout, error_checker=error_checker)
            except ChromeBrowserException as chrome_browser_exception:
                error = chrome_browser_exception
            if error:
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
            timeout += 1000 * options["delayToCheckUndeterminisms"]
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
        return decoded_response.get("result")
