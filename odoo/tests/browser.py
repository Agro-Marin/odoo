"""Chrome DevTools Protocol client for browser-based tests.

Extracted from :mod:`odoo.tests.common`: drives a headless Chrome through the
CDP websocket (page navigation, console/error capture, screenshots and
screencasts) for :class:`odoo.tests.common.HttpCase` tours and JS suites.
``ChromeBrowser`` and ``ChromeBrowserException`` remain re-exported from
``odoo.tests.common`` for compatibility (including as mock/patch targets).
"""

import binascii
import concurrent.futures
import contextlib
import gc
import itertools
import json
import logging
import os
import pathlib
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import CancelledError, Future, InvalidStateError, wait
from datetime import datetime
from functools import lru_cache
from itertools import islice, zip_longest
from textwrap import shorten
from typing import TYPE_CHECKING, Any

import psutil
import requests

import odoo.tools
from odoo.tools.misc import find_in_path

from .utils import HOST, get_db_name, save_test_file

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from .common import HttpCase

try:
    import websocket
except ImportError:
    # chrome headless tests will be skipped
    websocket = None

_logger = logging.getLogger(__name__)

CHECK_BROWSER_SLEEP = 0.1  # seconds
CHECK_BROWSER_ITERATIONS = 100
BROWSER_WAIT = CHECK_BROWSER_SLEEP * CHECK_BROWSER_ITERATIONS  # seconds
DEFAULT_SUCCESS_SIGNAL = "test successful"

IGNORED_MSGS = re.compile(
    r"""
    failed\ to\ fetch  # base error
  | connectionlosterror:  # conversion by offlineFailToFetchErrorHandler
    # ``ConnectionLostError`` subclasses (web/static/src/core/network/rpc.js).
    # Each overrides ``this.name``, so the bare ``connectionlosterror:`` above
    # never matches their serialized form even though they ARE connection-lost
    # errors -- rpc.js extends the base class precisely so existing handling
    # keeps matching. Tearing the HTTP server down under an in-flight fetch
    # truncates the body, which rpc.js classifies as InvalidResponseError
    # ("empty 200, truncated proxy body"); that surfaced as a spurious ERROR
    # on every mail discuss tour run.
  | serveroverloaderror:
  | invalidresponseerror:
  | assetsloadingerror:  # lazy loaded bundle
""",
    flags=re.VERBOSE | re.IGNORECASE,
).search


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
        # both "1366x768" and "1366,768" occur in the wild: the old code
        # normalized by *mutating* test_case.browser_size, so tests were
        # written against either form — accept both, mutate nothing
        width, height = (
            int(size) for size in re.split(r"[x,]", test_case.browser_size)
        )
        self._websocket_request(
            "Emulation.setDeviceMetricsOverride",
            params={
                "mobile": False,
                "width": width,
                "height": height,
                "deviceScaleFactor": 1,
            },
        )

    def signal_handler(self, sig: int, frame: Any) -> None:
        """Handle SIGXCPU by stopping Chrome and exiting."""
        if sig == signal.SIGXCPU:
            _logger.info("CPU time limit reached, stopping Chrome and shutting down")
            self.stop()
            # sys.exit, not the site-provided exit() builtin: same SystemExit
            # semantics, but always available (python -S, frozen builds)
            sys.exit()

    def throttle(self, factor: int | None) -> None:
        if not factor:
            return

        assert 1 <= factor <= 50  # arbitrary upper limit
        self.throttling_factor = factor
        self._websocket_request(
            "Emulation.setCPUThrottlingRate", params={"rate": factor}
        )

    def stop(self) -> None:
        """Stop the Chrome browser process and clean up resources.

        Idempotent: ``browser_js`` registers it both as an early safety-net
        cleanup (covering failures during page/session setup) and at its
        ordering-sensitive happy-path position; the second call is a no-op.
        """
        if getattr(self, "_stopped", False):
            return
        self._stopped = True
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
        # deadline on the clock, not on summed sleep()s: each requests.get may
        # itself take up to 3s, which the old accounting ignored
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.chrome.poll() is not None:
                message = "Chrome crashed at startup"
                break
            try:
                r = requests.get(url, timeout=3)
                if r.ok:
                    return r.json()
                message = f"Chrome debugger answered with HTTP {r.status_code}"
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
        self, method: str, *, params: dict | None = None, timeout: float | None = None
    ) -> Any:
        """Send a CDP command and wait for its response.

        ``timeout`` is **wall-clock** seconds; the default (None -> 10s) is
        scaled by the CPU-throttling factor.  Callers converting a logical
        budget to wall-clock time must apply ``throttling_factor`` themselves,
        exactly once — the old signature scaled every value passed in, so
        pre-scaled budgets from ``_wait_ready``/``_wait_code_ok`` were
        multiplied by the factor *squared*.
        """
        assert threading.get_ident() != self._receiver.ident, (
            "_websocket_request must not be called from the consumer thread"
        )
        if not hasattr(self, "ws"):
            return None

        if timeout is None:
            timeout = 10.0 * self.throttling_factor
        f = self._websocket_send(method, params=params, with_future=True)
        try:
            return f.result(timeout=timeout)
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
        except OSError:  # includes BrokenPipeError / ConnectionResetError
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
        timeout *= self.throttling_factor  # wall-clock budget, scaled once
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
            except TimeoutError:
                # a ready code that is itself a never-resolving promise blocks
                # the evaluate for the remaining budget; honour the documented
                # bool contract instead of letting the TimeoutError escape
                result = "evaluate timeout"
                continue

            if result == {"type": "boolean", "value": True}:
                if taken > 2:
                    self._logger.info(
                        "The ready code took too much time: %.2fs",
                        time.time() - start_time,
                    )
                return True

            # not ready yet: without this pause the loop hammers the CDP
            # socket with thousands of evaluate round-trips per second
            time.sleep(0.05)

        exc = self._result.done() and self._result.exception()
        if exc:
            raise exc from None
        self.take_screenshot(prefix="sc_failed_ready_")
        self._logger.info("Ready code last try result: %s", result)
        return False

    def _wait_code_ok(
        self, code: str, timeout: float, error_checker: Callable | None = None
    ) -> None:
        timeout *= self.throttling_factor  # wall-clock budget, scaled once
        self.error_checker = error_checker
        self._logger.info('Evaluate test code "%s"', code)
        start = time.time()
        try:
            res = self._websocket_request(
                "Runtime.evaluate",
                params={
                    "expression": code,
                    "awaitPromise": True,
                },
                timeout=timeout,
            )["result"]
        except TimeoutError as evaluate_timeout:
            # the code itself outlived the budget (its promise never
            # resolved).  Capture diagnostics and raise the browser exception
            # like any other timeout — a bare TimeoutError used to escape
            # browser_js's handler, failing the test without a screenshot.
            self.take_screenshot()
            self.screencaster.save()
            raise ChromeBrowserException(
                "Script timeout exceeded"
            ) from evaluate_timeout
        if res.get("subtype") == "error":
            raise ChromeBrowserException("Running code returned an error: %s" % res)

        err = ChromeBrowserException("failed")
        try:
            # wait for the success signal/failure on the budget *remaining*
            # after the evaluate phase.  `time.time() - start + timeout` — the
            # sign flipped from the intended `start + timeout - time.time()` —
            # granted elapsed+timeout more, so a hung run blocked for the
            # evaluate duration twice over on top of the configured timeout.
            if (
                self._result.result(max(0.0, start + timeout - time.time()))
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
            "Page.navigate",
            params={"url": url},
            timeout=20.0 * self.throttling_factor,
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
        # Wait for in-flight frames; there is no CDP event marking the last
        # one, so poll for quiescence (no new frame for 0.5s) instead of the
        # old flat 5s sleep, which taxed every failing screencasted test.
        deadline = time.time() + 5
        frame_count = -1
        while time.time() < deadline and len(self.frames) != frame_count:
            frame_count = len(self.frames)
            time.sleep(0.5)
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
    browser_bin_path = os.environ.get(
        "ODOO_BROWSER_BIN"
    )  # used for testing specific Chrome builds
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
