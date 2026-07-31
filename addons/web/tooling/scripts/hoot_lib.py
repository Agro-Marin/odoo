"""Shared helpers for the warm-server HOOT runner.

This module is imported by the ``hoot`` and ``hoot-affected`` CLI scripts. It
must be run with the workspace venv interpreter (the CLI shebang trampolines
re-exec with it automatically; override with ``$ODOO_VENV_PYTHON``) because it
imports the Odoo
framework to reuse ``odoo.tests.common.ChromeBrowser`` (the exact CDP driver the
real ``odoo-bin`` test loop uses) instead of reinventing a Chrome DevTools
client.

Nothing here edits Odoo core; ``ChromeBrowser`` is imported and driven as-is
through a tiny shim object that provides the three attributes it reads off a
test case (``_logger``, ``browser_size``, ``touch_enabled``) plus a
``fetch_proxy`` for external requests.
"""

from __future__ import annotations

import contextlib
import fcntl
import getpass
import json
import logging
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
ODOO_ROOT = _SCRIPT_DIR.parents[3]
WORKSPACE = ODOO_ROOT.parents[1]
VENV_PY = Path(os.environ.get("ODOO_VENV_PYTHON", sys.executable))
ODOO_BIN = ODOO_ROOT / "odoo-bin"


def _find_conf() -> Path:
    override = os.environ.get("ODOO_CONF")
    if override:
        return Path(override)
    venv_name = VENV_PY.parent.parent.name
    candidate = WORKSPACE / "config" / f"{venv_name}.conf"
    if candidate.exists():
        return candidate
    confs = sorted((WORKSPACE / "config").glob("*.conf"))
    if len(confs) == 1:
        return confs[0]
    raise SystemExit(
        f"hoot: cannot pick a config under {WORKSPACE / 'config'} "
        f"(no {candidate.name}, found {[c.name for c in confs]}); set $ODOO_CONF"
    )


CONF = _find_conf()

PORT_RANGE = range(8085, 8100)
DEFAULT_DB = "hoot_web"
HOST = "127.0.0.1"

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPT_DIR / ".hoot_state.json"
LOG_DIR = SCRIPT_DIR / ".hoot_logs"

ALWAYS_MODULES = ("web",)

DEV_FLAGS = "--dev=assets,qweb"
"""Watch asset sources and invalidate on change, with the asset caches left
enabled. ``--dev=xml`` would give the same live reload by disabling those
caches instead, at ~4.5x per ``/web/tests`` render."""

SUCCESS_SIGNAL = "[HOOT] Test suite succeeded"
RE_FAILED_TEST = re.compile(r'Test "(.+?)" failed')
RE_PASSED_TEST = re.compile(r'Test "(.+?)" passed')
RE_FAILED_SUMMARY = re.compile(r"Failed (\d+) tests \((\d+) passed")
RE_PASSED_SUMMARY = re.compile(r"Passed (\d+) tests \((\d+) assertions")

_log = logging.getLogger("hoot")


def generate_hash(test_string: str) -> str:
    """Return the 8-hex-char HOOT id for a suite/test path.

    Byte-for-byte identical to ``HOOTCommon._generate_hash`` so the ids this
    runner sends match what ``odoo-bin --test-tags`` would send.
    """
    hash_val = 0
    for char in test_string:
        hash_val = (hash_val << 5) - hash_val + ord(char)
        hash_val &= 0xFFFFFFFF
    return f"{hash_val:08x}"


PG_USER = os.environ.get("PGUSER") or getpass.getuser()


def _psql(sql: str) -> str:
    out = subprocess.run(
        ["psql", "-U", PG_USER, "-d", "postgres", "-tAc", sql],
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout.strip()


def db_exists(db: str) -> bool:
    return _psql(f"SELECT 1 FROM pg_database WHERE datname='{db}'") == "1"


def drop_db(db: str) -> None:
    subprocess.run(
        [
            "psql",
            "-U",
            PG_USER,
            "-d",
            "postgres",
            "-c",
            f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)',
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((HOST, port))
            return True
        except OSError:
            return False


_PORT_LOCKS: dict[int, object] = {}


def _reserve_port(port: int) -> bool:
    """Claim ``port`` for this process, cross-process. False if someone else
    is already booting on it."""
    if port in _PORT_LOCKS:
        return True
    LOG_DIR.mkdir(exist_ok=True)
    handle = (LOG_DIR / f".port_{port}.lock").open("w")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False
    _PORT_LOCKS[port] = handle
    return True


def _release_port(port: int) -> None:
    handle = _PORT_LOCKS.pop(port, None)
    if handle is not None:
        handle.close()


def _http_alive(port: int) -> bool:
    try:
        import requests

        resp = requests.get(
            f"http://{HOST}:{port}/web/login", timeout=2, allow_redirects=False
        )
        return resp.status_code < 500
    except Exception:
        return False


def addons_for_suites(suites: list[str]) -> set[str]:
    """Return the addon names referenced by ``@addon/...`` suite/test paths."""
    addons: set[str] = set()
    for suite in suites:
        m = re.match(r"^@([A-Za-z0-9_]+)(?:/|$)", suite.strip())
        if m:
            addons.add(m[1])
    return addons


def modules_for_suites(suites: list[str]) -> tuple[str, ...]:
    """Modules the warm DB must have installed to run ``suites``."""
    return tuple(sorted(set(ALWAYS_MODULES) | addons_for_suites(suites)))


def module_scope_param(suites: list[str]) -> str:
    """Return the ``&module_scope=`` param for a run, or ``""``.

    Mirrors ``web/tests/test_js.py::_get_module_scope_param`` so this runner
    loads the same bundle the ``web_js`` gate does. Without it the unit-test
    page executes the ``src`` of every installed addon, whose ``patch()`` calls
    are global and unconditional: a test asserting the RPCs of its own addon
    then sees a step from an addon outside its closure and fails here while
    passing under ``odoo-bin``.

    Suites spanning several addons have no single closure, so they stay
    unscoped rather than dropping one side's ``src``.
    """
    addons = addons_for_suites(suites)
    return f"&module_scope={addons.pop()}" if len(addons) == 1 else ""


def db_for_modules(modules: tuple[str, ...]) -> str:
    """Deterministic warm-DB name for a module set.

    ``{web}`` keeps the historical ``hoot_web``; anything more becomes
    ``hoot_<extra>_<extra>...`` so each combination gets its own disposable
    DB (concurrent warm servers never fight over one database).
    """
    extras = [m for m in modules if m not in ALWAYS_MODULES]
    return DEFAULT_DB if not extras else "hoot_" + "_".join(sorted(extras))


def state_file(db: str) -> Path:
    if db == DEFAULT_DB:
        return STATE_FILE
    return SCRIPT_DIR / f".hoot_state_{db}.json"


def read_state(db: str = DEFAULT_DB) -> dict | None:
    path = state_file(db)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return None
    return None


def read_all_states() -> list[dict]:
    states = []
    for path in sorted(SCRIPT_DIR.glob(".hoot_state*.json")):
        try:
            states.append(json.loads(path.read_text()))
        except json.JSONDecodeError:
            continue
    return states


def write_state(state: dict) -> None:
    state_file(state["db"]).write_text(json.dumps(state, indent=2))


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def server_is_warm(state: dict | None) -> bool:
    if not state:
        return False
    return _pid_alive(state.get("pid", -1)) and _http_alive(state["port"])


def installed_modules(db: str) -> set[str]:
    if not db_exists(db):
        return set()
    out = subprocess.run(
        [
            "psql",
            "-U",
            PG_USER,
            "-d",
            db,
            "-tAc",
            "SELECT name FROM ir_module_module WHERE state='installed'",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return set(out.stdout.split())


def _odoo_install(db: str, modules: tuple[str, ...], log_path: Path) -> None:
    cmd = [
        str(VENV_PY),
        str(ODOO_BIN),
        "-c",
        str(CONF),
        "-d",
        db,
        "-i",
        ",".join(("base", *modules)),
        "--stop-after-init",
        "--no-http",
        "--max-cron-threads=0",
    ]
    with log_path.open("wb") as fh:
        proc = subprocess.run(
            cmd,
            stdout=fh,
            stderr=subprocess.STDOUT,
            cwd=str(ODOO_ROOT),
            check=False,
        )
    if proc.returncode != 0 or not db_exists(db):
        raise RuntimeError(
            f"Database init failed (rc={proc.returncode}); see {log_path}"
        )


def ensure_db(
    db: str, modules: tuple[str, ...] = ALWAYS_MODULES, verbose: bool = False
) -> None:
    """Create ``db`` with ``modules`` installed; top up a DB that exists but
    is missing some of them (that path requires the DB's warm server, if any,
    to be stopped first — ``ensure_server`` handles that ordering)."""
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"init_{db}.log"
    if not db_exists(db):
        _log.info(
            "Creating database %s and installing %s (one-time)...",
            db,
            ",".join(modules),
        )
        _odoo_install(db, modules, log_path)
        return
    missing = set(modules) - installed_modules(db)
    if missing:
        _log.info(
            "Installing missing modules into %s: %s", db, ",".join(sorted(missing))
        )
        _odoo_install(db, tuple(sorted(missing)), log_path)


def boot_server(
    db: str, modules: tuple[str, ...] = ALWAYS_MODULES, verbose: bool = False
) -> dict:
    """Boot ONE persistent threaded dev server on a free port of PORT_RANGE."""
    ensure_db(db, modules, verbose=verbose)
    errors = []
    for port in PORT_RANGE:
        if not port_is_free(port) or not _reserve_port(port):
            continue
        try:
            return _boot_server_on(db, port)
        except RuntimeError as exc:
            _release_port(port)
            errors.append(f"{port}: {exc}")
    raise RuntimeError(
        f"No usable port in {PORT_RANGE.start}-{PORT_RANGE.stop - 1}"
        + ("; ".join(("", *errors)) if errors else "")
    )


def _boot_server_on(db: str, port: int) -> dict:
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"server_{db}.log"
    cmd = [
        str(VENV_PY),
        str(ODOO_BIN),
        "-c",
        str(CONF),
        "-d",
        db,
        "-p",
        str(port),
        "--http-interface",
        HOST,
        f"--db-filter=^{db}$",
        "--max-cron-threads=0",
        DEV_FLAGS,
    ]
    _log.info("Booting warm server: db=%s port=%s (log: %s)", db, port, log_path)
    log_fh = log_path.open("wb")
    proc = subprocess.Popen(
        cmd,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        cwd=str(ODOO_ROOT),
        start_new_session=True,
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"Server exited early (rc={proc.returncode}); see {log_path}"
            )
        if _http_alive(port):
            break
        time.sleep(0.5)
    else:
        proc.terminate()
        raise RuntimeError(f"Server did not become ready; see {log_path}")

    state = {
        "pid": proc.pid,
        "port": port,
        "db": db,
        "log": str(log_path),
        "started": time.time(),
    }
    write_state(state)
    return state


def _boot_flags_stale(state: dict) -> bool:
    """True when the live server was booted with different ``--dev`` flags.

    A server started before ``--dev=assets`` existed still runs ``--dev=xml``,
    whose asset caches are disabled — it would keep paying the 4.5x render cost
    forever. Recycling it once makes the speedup land without anyone having to
    know to restart their warm server.
    """
    try:
        cmdline = Path(f"/proc/{state['pid']}/cmdline").read_bytes()
    except OSError:
        return False
    return DEV_FLAGS.encode() not in cmdline


def ensure_server(
    db: str | None, modules: tuple[str, ...] = ALWAYS_MODULES, verbose: bool = False
) -> tuple[dict, bool]:
    """Return (state, booted). Reuse this DB's warm server if it is alive
    and already has every required module installed."""
    db = db or db_for_modules(modules)
    state = read_state(db)
    if server_is_warm(state) and state["db"] == db:
        missing = set(modules) - installed_modules(db)
        if missing:
            _log.info(
                "Warm server on %s lacks modules %s - recycling",
                db,
                ",".join(sorted(missing)),
            )
            stop_server(db)
        elif _boot_flags_stale(state):
            _log.info("Warm server on %s predates %s - recycling", db, DEV_FLAGS)
            stop_server(db)
        else:
            return state, False
    state = boot_server(db, modules, verbose=verbose)
    return state, True


def _terminate_pid(pid: int) -> None:
    try:
        import psutil

        main = psutil.Process(pid)
        procs = [main, *main.children(recursive=True)]
        main.terminate()
        _, alive = psutil.wait_procs(procs, 5)
        for p in alive:
            p.kill()
    except Exception:
        with contextlib.suppress(OSError):
            os.killpg(os.getpgid(pid), 15)


def stop_server(db: str | None = None, clean: bool = False) -> str:
    """Stop one DB's warm server (or every recorded one when db is None)."""
    states = [s for s in read_all_states() if db is None or s.get("db") == db]
    if not states:
        return "No warm server recorded."
    msg = []
    for state in states:
        pid, port, sdb = state.get("pid"), state.get("port"), state.get("db")
        if pid and _pid_alive(pid):
            _terminate_pid(pid)
            msg.append(f"Stopped server pid={pid} port={port} db={sdb}.")
        else:
            msg.append(f"Server for {sdb} was not running.")
        if sdb:
            state_file(sdb).unlink(missing_ok=True)
        if clean and sdb:
            drop_db(sdb)
            msg.append(f"Dropped database {sdb}.")
    return " ".join(msg)


class _ConsoleCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


class _ShimCase:
    """Minimal stand-in for the ``test_case`` ChromeBrowser expects.

    ChromeBrowser only reads ``_logger``, ``browser_size``, ``touch_enabled``
    off its test case, and calls ``fetch_proxy(url)`` for requests that leave
    the local host. Requests to ``http://127.0.0.1[:port]`` are continued
    verbatim by ChromeBrowser itself, so they hit the real warm server.

    ``fetch_proxy``/``make_fetch_proxy_response`` are *grafted from HttpCase*
    rather than reimplemented. A local blanket-404 version silently diverged
    from the canonical one, which answers ``https://fonts.googleapis.com/css``
    with an empty 200 stylesheet: a bundle whose CSS starts with Google-Fonts
    ``@import`` rules (``website.website_builder_assets`` has six) then had
    those imports 404, Chrome propagated the failure to the owner ``<link>``,
    and every ``loadBundle()`` of it rejected -- which failed the whole
    ``@website/builder`` tree here while it passed under ``odoo-bin``. Both
    methods only touch their arguments and the module logger, so binding them
    is safe and keeps the runner faithful to the real loop by construction.
    """

    def __init__(
        self, logger: logging.Logger, browser_size: str, touch_enabled: bool
    ) -> None:
        self._logger = logger
        self.browser_size = browser_size
        self.touch_enabled = touch_enabled

    @property
    def _http_case(self):
        from odoo.tests.common import HttpCase

        return HttpCase

    def fetch_proxy(self, url: str) -> dict:
        return self._http_case.fetch_proxy(self, url)

    def make_fetch_proxy_response(self, content, code: int = 200) -> dict:
        return self._http_case.make_fetch_proxy_response(self, content, code)


def _bootstrap_odoo() -> None:
    """Prepare the in-process Odoo import so ChromeBrowser is usable."""
    if str(ODOO_ROOT) not in sys.path:
        sys.path.insert(0, str(ODOO_ROOT))
    import odoo.logutils  # noqa: F401  (registers Logger.runbot)
    from odoo.tools import config

    config["screencasts"] = ""
    if not config.get("screenshots"):
        config["screenshots"] = tempfile.mkdtemp(prefix="hoot_shots_")


def _authenticate(port: int, db: str) -> str:
    """Log in as admin/admin over HTTP and return the session_id cookie."""
    import requests

    resp = requests.post(
        f"http://{HOST}:{port}/web/session/authenticate",
        json={
            "jsonrpc": "2.0",
            "params": {"db": db, "login": "admin", "password": "admin"},
        },
        timeout=30,
    )
    resp.raise_for_status()
    sid = resp.cookies.get("session_id")
    if not sid:
        raise RuntimeError("Authentication failed: no session_id cookie")
    return sid


@dataclass
class RunResult:
    ok: bool
    suites: list[str]
    passed: int = 0
    failed: int = 0
    failed_tests: list[str] = field(default_factory=list)
    wall: float = 0.0
    error: str | None = None
    incomplete: bool = False
    repeated: int = 0
    """Re-executions observed on a truncated run: passed-lines minus distinct
    test names. Non-zero means the selection made HOOT run suites more than
    once, which is why such a run never reaches its summary."""


def run_suites(
    suites: list[str],
    *,
    port: int,
    db: str,
    preset: str = "desktop",
    hoot_timeout_ms: int = 15000,
    wall_timeout_s: int = 300,
    browser_size: str = "1366x768",
    touch_enabled: bool = False,
    extra: str = "",
    verbose: bool = False,
) -> RunResult:
    """Drive Chrome against the warm server's ``/web/tests`` and report."""
    _bootstrap_odoo()
    from odoo.tools import config

    config["db_name"] = [db]
    from odoo.tests.common import ChromeBrowser, ChromeBrowserException

    run_logger = logging.getLogger("hoot.run")
    run_logger.setLevel(logging.INFO if verbose else logging.WARNING)
    browser_logger = logging.getLogger("hoot.run.browser")
    browser_logger.setLevel(logging.INFO)
    prev_propagate = browser_logger.propagate
    if not verbose:
        browser_logger.propagate = False
    capture = _ConsoleCapture()
    browser_logger.addHandler(capture)

    id_filters = "".join(f"&id={generate_hash(s)}" for s in suites)
    url = (
        f"http://{HOST}:{port}/web/tests?headless&loglevel=2"
        f"&preset={preset}&timeout={hoot_timeout_ms}{id_filters}"
        f"{module_scope_param(suites)}{extra}"
    )

    def unit_test_error_checker(message: str) -> bool:
        return "[HOOT]" not in message

    shim = _ShimCase(run_logger, browser_size, touch_enabled)
    start = time.time()
    result = RunResult(ok=False, suites=suites)
    browser = None
    try:
        sid = _authenticate(port, db)
        browser = ChromeBrowser(shim, success_signal=SUCCESS_SIGNAL, headless=True)
        browser.set_cookie("session_id", sid, "/", HOST, http_only=True)
        _log.info("Navigating: %s", url)
        browser.navigate_to(url, wait_stop=True)
        if not browser._wait_ready(""):
            raise RuntimeError("Page ready code was always falsy")
        browser._wait_code_ok("", wall_timeout_s, error_checker=unit_test_error_checker)
        result.ok = True
    except ChromeBrowserException as exc:
        text = str(exc)
        result.error = text.splitlines()[0] if text.strip() else "failed"
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        _log.debug("Unexpected runner error", exc_info=True)
    finally:
        if browser is not None:
            with contextlib.suppress(Exception):
                browser.stop()
        result.wall = time.time() - start
        browser_logger.removeHandler(capture)
        browser_logger.propagate = prev_propagate

    summary_seen = False
    # DISTINCT test names, not the number of "passed" lines. HOOT re-emits a
    # suite's tests when a coarse id selects overlapping suites, so the raw line
    # count is not a test count: on a truncated ``@web/core`` run it grew from
    # 30838 to 58569 purely by raising the wall-clock timeout, while the suite
    # only declares ~2400 tests. That number is what a caller reads as "N tests
    # passed", so it has to mean that.
    passed_names: set[str] = set()
    passed_lines = 0
    for line in capture.lines:
        if m := RE_FAILED_SUMMARY.search(line):
            result.failed, result.passed = int(m[1]), int(m[2])
            summary_seen = True
        elif m := RE_PASSED_SUMMARY.search(line):
            result.passed = int(m[1])
            summary_seen = True
        if m := RE_PASSED_TEST.search(line):
            passed_names.add(m[1])
            passed_lines += 1
        for name in RE_FAILED_TEST.findall(line):
            if name not in result.failed_tests:
                result.failed_tests.append(name)
    if not summary_seen and (passed_names or result.failed_tests):
        result.passed = len(passed_names)
        result.failed = len(result.failed_tests)
        result.repeated = passed_lines - len(passed_names)
        if not result.ok:
            result.incomplete = True
    if result.error and not result.ok:
        result.ok = False
    return result


WEB_ADDONS_ROOT = ODOO_ROOT / "addons"
RE_IMPORT = re.compile(
    r"""(?:import|export)\s+(?:.+?\s+from\s+)?["']([^"']+)["']""",
    re.DOTALL,
)
RE_DYNAMIC_IMPORT = re.compile(r"""import\(\s*["']([^"']+)["']\s*\)""")


def _addon_of(path: Path) -> str | None:
    """Return the addon name for a file under ``.../<addon>/static/...``.

    Keyed off the ``static`` segment (the addon is the directory right before
    it) so nested ``addons/odoo/addons/web`` paths resolve correctly.
    """
    parts = path.parts
    if "static" in parts:
        i = parts.index("static")
        if i >= 1:
            return parts[i - 1]
    return None


def file_to_specifier(path: Path) -> str | None:
    """Map a src/tests JS file to its ESM import specifier.

    ``.../web/static/src/core/domain.js`` -> ``@web/core/domain``
    ``.../web/static/tests/core/domain.test.js`` -> ``@web/../tests/core/domain``
    """
    addon = _addon_of(path)
    if not addon:
        return None
    parts = path.parts
    i = parts.index("static")
    kind = parts[i + 1]
    rel = "/".join(parts[i + 2 :])
    rel = re.sub(r"\.js$", "", rel)
    if kind == "src":
        return f"@{addon}/{rel}"
    if kind == "tests":
        return f"@{addon}/../tests/{rel}"
    return None


def specifier_to_suite(spec: str) -> str | None:
    """Map a test-file specifier to the HOOT suite name it registers.

    Mirrors ``start.hoot.js`` ``_suiteNameFromSpecifier``:
    ``@web/../tests/core/domain.test`` -> ``@web/core/domain``.
    """
    m = re.match(r"^(@[^/]+)/\.\./tests/(.*?)(?:\.test)?$", spec)
    return f"{m[1]}/{m[2]}" if m else None


def _iter_test_files() -> list[Path]:
    files: list[Path] = []
    for addon_dir in WEB_ADDONS_ROOT.iterdir():
        tdir = addon_dir / "static" / "tests"
        if tdir.is_dir():
            files.extend(tdir.rglob("*.test.js"))
    return files


def _iter_src_files() -> list[Path]:
    files: list[Path] = []
    for addon_dir in WEB_ADDONS_ROOT.iterdir():
        sdir = addon_dir / "static" / "src"
        if sdir.is_dir():
            files.extend(sdir.rglob("*.js"))
    return files


def _imports_of(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    specs = set(RE_IMPORT.findall(text))
    specs |= set(RE_DYNAMIC_IMPORT.findall(text))
    return {s for s in specs if s.startswith("@")}


def changed_web_js(paths: list[str] | None = None) -> list[Path]:
    """Default set of changed JS files: ``git diff --name-only`` in addons/odoo,
    filtered to files under an addon ``static/`` tree.
    """
    if paths:
        return [Path(p).resolve() for p in paths]
    out = subprocess.run(
        ["git", "-C", str(ODOO_ROOT), "diff", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    names = out.stdout.splitlines()
    return [
        (ODOO_ROOT / name).resolve()
        for name in names
        if name.endswith(".js") and "/static/" in name
    ]


def affected_suites(changed: list[Path]) -> list[str]:
    """Return the minimal set of ``@web/...`` suite paths to run.

    Strategy (conservative import-scan, direct + one hop through src):
      * a changed *.test.js file -> its own suite;
      * a changed src file -> every test file importing it directly, plus test
        files importing a src file that imports the changed src (one hop).
    """
    changed_specs: set[str] = set()
    suites: set[str] = set()
    for path in changed:
        spec = file_to_specifier(path)
        if spec is None:
            continue
        if "/../tests/" in spec:
            suite = specifier_to_suite(spec)
            if suite:
                suites.add(suite)
        else:
            changed_specs.add(spec)

    if not changed_specs:
        return sorted(suites)

    hop_specs: set[str] = set()
    for src in _iter_src_files():
        imports = _imports_of(src)
        if imports & changed_specs:
            spec = file_to_specifier(src)
            if spec:
                hop_specs.add(spec)
    target_specs = changed_specs | hop_specs

    for test_file in _iter_test_files():
        if _imports_of(test_file) & target_specs:
            spec = file_to_specifier(test_file)
            suite = specifier_to_suite(spec) if spec else None
            if suite:
                suites.add(suite)
    return sorted(suites)
