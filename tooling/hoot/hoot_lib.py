from __future__ import annotations

import ast
import configparser
import contextlib
import fcntl
import getpass
import json
import logging
import os
import posixpath
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(SCRIPT_DIR.parent))
from _repo_root import find_odoo_root, find_workspace  # noqa: E402

ODOO_ROOT = find_odoo_root(SCRIPT_DIR, tool="hoot")
WORKSPACE = find_workspace(ODOO_ROOT)
VENV_PY = Path(os.environ.get("ODOO_VENV_PYTHON", sys.executable))
ODOO_BIN = ODOO_ROOT / "odoo-bin"


def _find_conf() -> Path | None:

    override = os.environ.get("ODOO_CONF")
    if override:
        return Path(override)
    if WORKSPACE is None:
        return None
    venv_name = VENV_PY.parent.parent.name
    search_dirs = [WORKSPACE / "config", WORKSPACE]
    for directory in search_dirs:
        candidate = directory / f"{venv_name}.conf"
        if candidate.exists():
            return candidate
    for directory in search_dirs:
        confs = sorted(directory.glob("*.conf"))
        if len(confs) == 1:
            return confs[0]
    return None


CONF = _find_conf()


def require_conf() -> Path:
    if CONF is None:
        where = (
            f"under {WORKSPACE} or {WORKSPACE / 'config'}"
            if WORKSPACE
            else "(repo-alone checkout: no workspace supplying a config)"
        )
        raise SystemExit(f"hoot: no odoo config found {where}; set $ODOO_CONF")
    return CONF


def _port_range() -> range:
    """The ports a warm server may claim.

    Fifteen was enough when one session ran tests. It is not enough now: a
    busy workspace holds every one of them, and the next session cannot run a
    suite at all -- `boot_server` raises "No usable port" and there is nothing
    to pass to make it try elsewhere. `$ODOO_HOOT_PORTS` is that something,
    spelt `first-last` (inclusive) or `first+count`.

    The default is widened rather than left at fifteen, because the failure it
    produces is total and the cost of a wider scan is one connect() per busy
    port.
    """
    spec = os.environ.get("ODOO_HOOT_PORTS", "").strip()
    if not spec:
        return range(8085, 8145)
    try:
        if "+" in spec:
            first, count = (int(part) for part in spec.split("+", 1))
            last = first + count - 1
        elif "-" in spec:
            first, last = (int(part) for part in spec.split("-", 1))
        else:
            first = last = int(spec)
        if not (0 < first <= last <= 65535):
            raise ValueError(spec)
    except ValueError:
        raise SystemExit(
            f"hoot: $ODOO_HOOT_PORTS={spec!r} is not 'first-last' or 'first+count'"
        ) from None
    return range(first, last + 1)


PORT_RANGE = _port_range()
DEFAULT_DB = "hoot_web"
HOST = "127.0.0.1"

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
RE_ASSET_URL = re.compile(r"/web/assets/[\w./-]+")

_log = logging.getLogger("hoot")

C_GREEN, C_RED, C_YEL, C_DIM, C_RST = (
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[2m",
    "\033[0m",
)


def color(txt: str, code: str) -> str:

    return f"{code}{txt}{C_RST}" if sys.stdout.isatty() else txt


def generate_hash(test_string: str) -> str:

    hash_val = 0
    units = test_string.encode("utf-16-le")
    for i in range(0, len(units), 2):
        hash_val = (hash_val << 5) - hash_val + (units[i] | units[i + 1] << 8)
        hash_val &= 0xFFFFFFFF
    return f"{hash_val:08x}"


PG_USER = os.environ.get("PGUSER") or getpass.getuser()


class PostgresUnavailable(RuntimeError):
    """The cluster could not be reached.

    Distinct from "the database is not there", and the distinction is the whole
    point: this box shares one PostgreSQL cluster between sessions and reaches
    ``max_connections`` routinely.  ``_psql`` used to discard ``returncode``
    and ``stderr`` and return ``""`` for every failure, so ``db_exists``
    answered *False* to "too many clients already" — and three things went
    wrong at once.  ``ensure_db`` decided the warm database was absent and
    re-installed it, ``installed_modules`` returned an empty set so every
    module looked missing, and ``_odoo_install`` reported
    ``Database init failed (rc=0)`` on a run whose log ends
    ``Modules loaded.``  A tool that cannot reach the cluster must say so.
    """


def _psql(sql: str) -> str:
    out = subprocess.run(
        ["psql", "-U", PG_USER, "-d", "postgres", "-tAc", sql],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        raise PostgresUnavailable(
            f"psql exited {out.returncode}: "
            f"{out.stderr.strip() or out.stdout.strip() or 'no output'}"
        )
    return out.stdout.strip()


_DB_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def check_db_name(db: str) -> str:

    if not _DB_NAME_RE.match(db):
        raise SystemExit(
            f"hoot: refusing database name {db!r} — expected only letters, "
            f"digits and underscores."
        )
    return db


def db_exists(db: str) -> bool:
    return (
        _psql(f"SELECT 1 FROM pg_database WHERE datname='{check_db_name(db)}'") == "1"
    )


def data_dir() -> Path | None:
    """``data_dir`` from the active config, or None if it does not say one.

    Returning None rather than guessing Odoo's default is deliberate: the only
    caller uses this to choose a directory to *delete*, and a guess that lands
    on the wrong tree deletes the wrong tree. Inline ``;``/``#`` comments are
    stripped, as the server's own parser does.
    """
    if CONF is None:
        return None
    parser = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    try:
        parser.read(CONF)
        raw = parser.get("options", "data_dir", fallback="").strip()
    except configparser.Error:
        return None
    return Path(raw).expanduser() if raw else None


def drop_filestore(db: str) -> bool:
    """Delete the filestore of a database being dropped.

    ``DROP DATABASE`` does not touch it, so every hoot database ever dropped
    left its attachments behind. One workspace had accumulated 109 such
    directories, 4.4 GB, every one belonging to a database that no longer
    existed -- invisible, because nothing ever looks there.

    Guarded rather than trusted, since this removes a tree: the name is
    already confined to ``[A-Za-z0-9_]+`` by ``check_db_name``, and the
    resolved path must still be a directory sitting *directly* inside
    ``<data_dir>/filestore``. Anything else is refused rather than removed.
    """
    root = data_dir()
    if root is None:
        return False
    store = (root / "filestore").resolve()
    target = (store / check_db_name(db)).resolve()
    if target.parent != store or not target.is_dir():
        return False
    shutil.rmtree(target, ignore_errors=True)
    _log.info("Removed filestore for %s (%s)", db, target)
    return True


def drop_db(db: str) -> None:
    out = subprocess.run(
        [
            "psql",
            "-U",
            PG_USER,
            "-d",
            "postgres",
            "-c",
            f'DROP DATABASE IF EXISTS "{check_db_name(db)}" WITH (FORCE)',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    # Only after the database is really gone: a filestore whose database still
    # exists is live data, not litter.
    if out.returncode == 0:
        drop_filestore(db)


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((HOST, port))
            return True
        except OSError:
            return False


_PORT_LOCKS: dict[int, object] = {}


LOG_RETENTION = 20


def _live_log_paths() -> set[Path]:
    live: set[Path] = set()
    for state in read_all_states():
        log, pid = state.get("log"), state.get("pid")
        if log and pid and _pid_alive(pid):
            live.add(Path(log))
    return live


def _prune_logs(keep: int = LOG_RETENTION) -> None:

    with contextlib.suppress(OSError):
        live = {p.resolve() for p in _live_log_paths()}
        logs = [
            p
            for p in sorted(
                LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True
            )
            if p.resolve() not in live
        ]
        for stale in logs[keep:]:
            with contextlib.suppress(OSError):
                stale.unlink()


def _reserve_port(port: int) -> bool:
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


@contextlib.contextmanager
def _boot_lock(db: str):
    """Serialise booting ONE database across every session on this box.

    The port locks make concurrent boots pick different ports; nothing made
    them pick different *databases*. A db has a single state file, so N
    sessions that all find no warm server all boot one, all write that file,
    and the last write wins -- leaving N-1 live servers with nothing pointing
    at them. Measured before this lock: 4 concurrent invocations produced 4
    servers, 1 record and 3 orphans, in one burst.

    ``flock`` rather than a lock file's existence, because the kernel releases
    it when the holder dies: a session killed mid-boot cannot wedge everyone
    else. Held across the whole boot on purpose -- that is the window being
    closed, and a waiter blocking is the correct outcome, since the thing it
    would otherwise do is boot a duplicate.
    """
    LOG_DIR.mkdir(exist_ok=True)
    handle = (LOG_DIR / f".boot_{check_db_name(db)}.lock").open("w")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            _log.info("Another session is booting %s -- waiting for it", db)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        handle.close()


HEALTH_TIMEOUT = 2.0
HEALTH_ATTEMPTS = 3
HEALTH_BACKOFF = 1.0


def _http_probe(port: int, timeout: float = HEALTH_TIMEOUT) -> str:
    """Probe one server once: ``up``, ``busy`` or ``down``.

    The three-way answer is the point. ``down`` means nothing is listening --
    instant and definitive, so there is nothing to wait for. ``busy`` means
    something IS there but did not answer in time, or answered 5xx; a heavy
    suite and a starved connection pool both produce that, and neither means
    the server is unusable. Collapsing the two into one boolean is what let a
    momentarily slow server be read as dead and replaced.
    """
    import requests

    try:
        resp = requests.get(
            f"http://{HOST}:{port}/web/login", timeout=timeout, allow_redirects=False
        )
    except requests.ConnectTimeout:
        # MUST precede ConnectionError, which it subclasses. On loopback a
        # refused connection is instant, so a handshake that times out means
        # the listen backlog is full -- an overloaded server, not an absent
        # one. Ordering these the other way round classified the busiest
        # servers as dead, which is the exact case this split exists to spare.
        return "busy"
    except requests.ConnectionError:
        return "down"
    except requests.RequestException:
        return "busy"
    return "up" if resp.status_code < 500 else "busy"


def _http_alive(port: int, timeout: float = HEALTH_TIMEOUT) -> bool:
    return _http_probe(port, timeout) == "up"


def _server_responsive(port: int, attempts: int = HEALTH_ATTEMPTS) -> bool:
    """Ask more than once before calling a server unusable.

    Only a ``busy`` verdict is retried: a refused connection cannot become an
    answer, so ``--status`` stays fast over dead entries.
    """
    for attempt in range(attempts):
        verdict = _http_probe(port)
        if verdict == "up":
            return True
        if verdict == "down":
            return False
        if attempt + 1 < attempts:
            time.sleep(HEALTH_BACKOFF)
    return False


def addons_for_suites(suites: list[str]) -> set[str]:
    addons: set[str] = set()
    for suite in suites:
        m = re.match(r"^@([A-Za-z0-9_]+)(?:/|$)", suite.strip())
        if m:
            addons.add(m[1])
    return addons


def modules_for_suites(suites: list[str]) -> tuple[str, ...]:
    return tuple(sorted(set(ALWAYS_MODULES) | addons_for_suites(suites)))


def module_scope_param(suites: list[str]) -> str:

    addons = addons_for_suites(suites)
    return f"&module_scope={addons.pop()}" if len(addons) == 1 else ""


def db_for_modules(modules: tuple[str, ...]) -> str:

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

    path = state_file(state["db"])
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(path)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def server_is_warm(state: dict | None) -> bool:
    if not state:
        return False
    return _pid_alive(state.get("pid", -1)) and _server_responsive(state["port"])


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
        str(require_conf()),
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
    if proc.returncode != 0:
        raise RuntimeError(
            f"Database init failed (rc={proc.returncode}); see {log_path}"
        )
    if not db_exists(db):
        raise RuntimeError(
            f"Database init exited 0 but {db!r} is not there; see {log_path}"
        )


def ensure_db(
    db: str, modules: tuple[str, ...] = ALWAYS_MODULES, verbose: bool = False
) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    _prune_logs()
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
    _prune_logs()
    log_path = LOG_DIR / f"server_{db}.log"
    cmd = [
        str(VENV_PY),
        str(ODOO_BIN),
        "-c",
        str(require_conf()),
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
    warn_if_no_watcher(log_path)
    return state


# The exact string ``service/lifecycle.py`` logs when the inotify watcher
# cannot start. Matching on it is deliberate: a server without a watcher serves
# whatever the sources were at boot, so every later run silently tests stale
# code -- a false PASS on a fix you just wrote, or a false FAIL on one you just
# reverted. The warning goes to the server log, which nobody reads during a
# green run, so it is repeated here where the answer is.
_WATCHER_FAILED = "Could not start the file watcher"


def warn_if_no_watcher(log_path: Path | str | None) -> bool:
    """Say so, loudly, if this server will not pick up source edits.

    Returns whether the warning fired, so callers and tests can assert on it.
    """
    if not log_path:
        # A state written before this check existed, or a fake one in a test:
        # nothing to read, nothing to say.
        return False
    try:
        if _WATCHER_FAILED not in Path(log_path).read_text(
            encoding="utf8", errors="replace"
        ):
            return False
    except OSError:
        return False
    try:
        limit = (
            Path("/proc/sys/fs/inotify/max_user_watches")
            .read_text(encoding="utf8")
            .strip()
        )
    except OSError:
        limit = "?"
    _log.warning(
        "This server has NO file watcher: source edits are NOT picked up, so "
        "every run tests the sources as they were at boot. "
        "fs.inotify.max_user_watches (%s) is per USER -- shared with your "
        "editor and with every other warm server. `hoot --status` lists them; "
        "stop some with `hoot --stop --db <name>`, or raise the limit, then "
        "`hoot --restart`. See %s.",
        limit,
        log_path,
    )
    return True


def _boot_flags_stale(state: dict) -> bool:

    try:
        cmdline = Path(f"/proc/{state['pid']}/cmdline").read_bytes()
    except OSError:
        return False
    return DEV_FLAGS.encode() not in cmdline


def _reclaim_recorded_server(db: str, state: dict | None) -> bool:
    """Stop a recorded server that is alive but failed its health check.

    ``boot_server`` ends in ``write_state``, and a db has exactly one state
    file. Booting a replacement while the recorded process is still running
    therefore does not replace that process -- it FORGETS it. The pid is then
    in no state file, so ``--status`` cannot show it, ``--stop --all`` cannot
    stop it and ``--clean`` cannot drop its db. The log is a second casualty:
    it is named per-DB, so the replacement opens the *same* path ``"wb"`` and
    truncates the running orphan's log, after which both write to one file at
    independent offsets.

    Left alone the leak compounds: every forgotten server keeps its psycopg
    pool and its inotify watches, so the cluster runs out of connection slots,
    the next health check reads 5xx as "dead", and another server is booted to
    join them. One workspace reached 16 servers on ``hoot_web`` and exhausted
    a 100-slot cluster this way.

    This closes one of the two ways a server was lost; ``_boot_lock`` closes
    the other, which is the unlocked window between "no warm server" and
    ``write_state``.

    Terminating first is safe because the caller has already established the
    server is not answering: ``_server_responsive`` retries a ``busy`` verdict
    before giving up, so a server that is merely slow is reused rather than
    replaced, and one that reaches here is of no use to anyone.

    Returns whether anything was terminated, for callers and tests.
    """
    if not state:
        return False
    pid = state.get("pid", -1)
    if not _pid_alive(pid):
        return False
    _log.warning(
        "Warm server for %s (pid %s, port %s) is alive but not answering -- "
        "stopping it before booting its replacement, so it cannot become an "
        "untracked orphan.",
        db,
        pid,
        state.get("port"),
    )
    _terminate_pid(pid)
    state_file(db).unlink(missing_ok=True)
    return True


def ensure_server(
    db: str | None, modules: tuple[str, ...] = ALWAYS_MODULES, verbose: bool = False
) -> tuple[dict, bool]:
    db = db or db_for_modules(modules)
    state = read_state(db)
    if server_is_warm(state) and state["db"] == db:
        try:
            missing = set(modules) - installed_modules(db)
        except PostgresUnavailable as exc:
            # A warm server answering HTTP is its own proof: it could not have
            # booted without the database and the modules. When the shared
            # cluster is out of connection slots we cannot re-verify, and the
            # old code read the resulting empty set as "no modules installed"
            # and RECYCLED the healthy server -- turning another session's
            # connection pressure into a cold rebuild that then failed to get
            # a connection either. Reuse is both correct and the only thing
            # that can succeed here.
            _log.info("Cannot re-verify %s (%s) - reusing the warm server", db, exc)
            warn_if_no_watcher(state.get("log"))
            return state, False
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
            # The reuse path is where a watcherless server does its damage:
            # "Reusing warm server" reads like everything is fine while the
            # bundle is frozen at boot time.
            warn_if_no_watcher(state.get("log"))
            return state, False
    return _boot_serialised(db, modules, verbose=verbose)


def _boot_serialised(
    db: str, modules: tuple[str, ...], verbose: bool = False
) -> tuple[dict, bool]:
    """Boot under the db's lock, re-checking once the lock is ours.

    The re-check is the half that matters. `ensure_server`'s inspection ran
    unlocked, so by the time we hold the lock another session may have booted
    exactly the server we were about to duplicate; reusing it is both correct
    and free. Without it the lock would merely stagger the duplicate boots
    rather than prevent them.

    Every mutation of this db's server happens here, under the lock -- reuse,
    recycle, reclaim and boot alike. That is the invariant worth keeping: a
    decision taken from an unlocked read can be stale by the time it is acted
    on, and acting on a stale read is what stranded the servers.
    """
    with _boot_lock(db):
        state = read_state(db)
        if server_is_warm(state) and state["db"] == db:
            try:
                missing = set(modules) - installed_modules(db)
            except PostgresUnavailable:
                # As in ensure_server: a server answering HTTP is its own
                # proof that its db and modules are there.
                missing = set()
            if not missing:
                _log.info("Another session booted %s while we waited - reusing", db)
                warn_if_no_watcher(state.get("log"))
                return state, False
            stop_server(db)
        else:
            # Not warm, but possibly not dead either -- one of the two ways a
            # server was being lost. See _reclaim_recorded_server.
            _reclaim_recorded_server(db, state)
        return boot_server(db, modules, verbose=verbose), True


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


_DB_FILTER_RE = re.compile(r"^--db-filter=\^(\w+)\$$")


def find_server_processes() -> dict[int, str]:
    """Every running warm server of THIS checkout, read from /proc.

    The state files are the record of what was booted; this is the ground
    truth. They disagree whenever a record was lost, and only the ground truth
    can find a server nothing points at any more.

    Matching is deliberately tied to ``ODOO_BIN``, so a sibling workspace's
    servers -- and anything else on the box -- are none of our business.
    """
    servers: dict[int, str] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = (
                (entry / "cmdline").read_bytes().decode("utf8", "replace").split("\0")
            )
        except OSError:
            continue  # exited between iterdir and read: not our problem
        if str(ODOO_BIN) not in argv or "--max-cron-threads=0" not in argv:
            continue
        for arg in argv:
            match = _DB_FILTER_RE.match(arg)
            if match:
                servers[int(entry.name)] = match.group(1)
                break
    return servers


ORPHAN_GRACE = 180.0
"""How old an unrecorded server must be before it counts as an orphan.

``write_state`` runs only once the server answers HTTP, so throughout a boot --
12-25s in practice, up to the 120s deadline in ``_boot_server_on`` -- a
perfectly healthy server is recorded nowhere. Without a grace period longer
than that deadline, ``--status`` labels every booting server ORPHAN and
``--stop --all`` kills a session's boot mid-flight. Observed as a phantom
orphan that had vanished by the next sample.
"""


def _process_age(pid: int) -> float:
    """Seconds since the process started, or 0.0 if it cannot be read.

    0.0 means "too young to judge", which keeps an unreadable process out of
    the orphan list rather than into it: the list feeds a kill.
    """
    try:
        return max(0.0, time.time() - Path(f"/proc/{pid}").stat().st_ctime)
    except OSError:
        return 0.0


def find_untracked_servers(grace: float = ORPHAN_GRACE) -> dict[int, str]:
    """Running warm servers, old enough to have finished booting, that no
    state file accounts for."""
    tracked = {s.get("pid") for s in read_all_states()}
    return {
        pid: db
        for pid, db in find_server_processes().items()
        if pid not in tracked and _process_age(pid) >= grace
    }


def stop_untracked_servers(clean: bool = False) -> str:
    """Reap orphans -- servers running with nothing pointing at them.

    Only ever called from an explicit ``--stop/--clean --all``. An untracked
    server has no owner by construction, but a session that booted one
    microseconds ago has not written its state file yet, and reaping on the
    ordinary boot path would race it.
    """
    orphans = find_untracked_servers()
    if not orphans:
        return ""
    msg = []
    for pid, db in sorted(orphans.items()):
        _terminate_pid(pid)
        msg.append(f"Reaped untracked server pid={pid} db={db}.")
        if clean:
            drop_db(db)
            msg.append(f"Dropped database {db}.")
    return " ".join(msg)


class _ConsoleCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


class _ShimCase:
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
    if str(ODOO_ROOT) not in sys.path:
        sys.path.insert(0, str(ODOO_ROOT))
    import odoo.logutils  # noqa: F401  (registers Logger.runbot)
    from odoo.tools import config

    config["screencasts"] = ""
    if not config.get("screenshots"):
        config["screenshots"] = tempfile.mkdtemp(prefix="hoot_shots_")


def _authenticate(port: int, db: str) -> str:
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


def warm_bundles(port: int, db: str, scope_params: Iterable[str]) -> float:

    import requests

    start = time.time()
    session = requests.Session()
    session.cookies.set("session_id", _authenticate(port, db))
    for scope in dict.fromkeys(scope_params):
        url = f"http://{HOST}:{port}/web/tests?headless&loglevel=2{scope}"
        try:
            page = session.get(url, timeout=600)
            page.raise_for_status()
            for asset in dict.fromkeys(RE_ASSET_URL.findall(page.text)):
                session.get(f"http://{HOST}:{port}{asset}", timeout=600).close()
        except Exception as exc:
            _log.warning("Bundle warmup failed for %s: %s", url, exc)
    return time.time() - start


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
    server_died: bool = False
    """The warm server this ran against was gone by the end of it. Every test
    still to be configured then fails in `MockServer._loadModels` with
    `TypeError: Failed to fetch`, which reads as a wall of ordinary test
    failures and is not one. Measured cause on this box: the per-user inotify
    instance cap (128, shared with the desktop and every editor), which the
    server hits and dies on -- `OSError: [Errno 28] inotify is out of
    capacity`. A result with this set says nothing about the code."""


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
        f"&preset={preset}&timeout={hoot_timeout_ms}"
        f"{id_filters}{module_scope_param(suites)}{extra}"
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

    return summarise(capture.lines, result)


def summarise(lines: list[str], result: RunResult) -> RunResult:

    summary_seen = False
    passed_names: set[str] = set()
    passed_lines = 0
    for line in lines:
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


def _addons_roots() -> list[Path]:

    roots: list[Path] = []
    if CONF is not None:
        with contextlib.suppress(OSError):
            for line in CONF.read_text(encoding="utf-8").splitlines():
                key, sep, value = line.partition("=")
                if sep and key.strip() == "addons_path":
                    roots = [Path(p.strip()) for p in value.split(",") if p.strip()]
                    break
    roots = [r for r in roots if r.is_dir()]
    return roots or [ODOO_ROOT / "addons"]


ADDONS_ROOTS = _addons_roots()
WEB_ADDONS_ROOT = ODOO_ROOT / "addons"

sys.path.insert(0, str(SCRIPT_DIR.parent / "architecture"))
from js_layer_check import collect_imports  # noqa: E402


def _addon_of(path: Path) -> str | None:

    parts = path.parts
    if "static" in parts:
        i = parts.index("static")
        if i >= 1:
            return parts[i - 1]
    return None


def file_to_specifier(path: Path) -> str | None:

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

    m = re.match(r"^(@[^/]+)/\.\./tests/(.*?)(?:\.test)?$", spec)
    return f"{m[1]}/{m[2]}" if m else None


@cache
def iter_addon_dirs() -> tuple[Path, ...]:

    dirs: list[Path] = []
    for root in ADDONS_ROOTS:
        with contextlib.suppress(OSError):
            dirs.extend(d for d in root.iterdir() if d.is_dir())
    return tuple(dirs)


def _iter_static_files(kind: str, pattern: str) -> list[Path]:
    files: list[Path] = []
    for addon_dir in iter_addon_dirs():
        d = addon_dir / "static" / kind
        if d.is_dir():
            files.extend(d.rglob(pattern))
    return files


def _iter_test_files() -> list[Path]:
    return _iter_static_files("tests", "*.test.js")


def _iter_src_files() -> list[Path]:
    return _iter_static_files("src", "*.js")


def ci_runner_suites(addon: str | None = None) -> set[str]:

    prefixes: set[str] = set()
    for addon_dir in iter_addon_dirs():
        if addon and addon_dir.name != addon:
            continue
        runner = addon_dir / "tests" / "test_js.py"
        if not runner.is_file():
            continue
        with contextlib.suppress(OSError, SyntaxError):
            prefixes |= _run_hoot_args(ast.parse(runner.read_text()))
    return prefixes


def mobile_suites(prefixes: list[str]) -> list[str]:

    _bootstrap_odoo()
    import odoo.modules.module

    odoo.modules.module.initialize_sys_path()
    from odoo.addons.web.tests.test_js import _mobile_suites_under

    return sorted(_mobile_suites_under(sorted(prefixes)))


def _run_hoot_args(tree: ast.Module) -> set[str]:
    constants: dict[str, tuple[str, ...]] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Tuple | ast.List)
        ):
            values: list[str] = []
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    values.append(elt.value)
                elif isinstance(elt, ast.Starred) and isinstance(elt.value, ast.Name):
                    values.extend(constants.get(elt.value.id, ()))
            constants[node.targets[0].id] = tuple(values)
    prefixes: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_run_hoot"
        ):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    prefixes.add(arg.value)
                elif isinstance(arg, ast.Starred) and isinstance(arg.value, ast.Name):
                    prefixes.update(constants.get(arg.value.id, ()))
    return prefixes


RE_MOBILE_TAG = re.compile(r"""\.tags\([^)]*["']mobile["']""")
"""A `mobile`-tagged test, matched exactly as `MobileWebSuite` matches one.

A second copy of that pattern, kept honest by
`test_hoot_lib.py::test_the_mobile_tag_pattern_matches_the_suites_own`: reaching
for the original costs an odoo bootstrap, which is the wrong price for a hint
printed after a passing run.
"""


def mobile_tagged_files(suites: list[str]) -> list[Path]:
    """The selected test files that own at least one `mobile`-tagged test.

    The desktop preset does not run them: HOOT selects by tag, and the two
    presets execute different sets -- "neither a superset of the other", as the
    README puts it, which is why it also says verifying a change means running
    the same suite list under both. That advice is easy to follow and easier to
    forget, and forgetting it is silent: a mobile-only test that fails is simply
    not in the desktop count.
    """
    found = []
    for suite in suites:
        for path in suite_test_files(suite):
            try:
                if RE_MOBILE_TAG.search(path.read_text(encoding="utf-8")):
                    found.append(path)
            except OSError:
                continue
    return sorted(set(found))


def suite_test_files(suite: str) -> list[Path]:
    addon, _, rel = suite.lstrip("@").partition("/")
    for addon_dir in iter_addon_dirs():
        if addon_dir.name != addon:
            continue
        tests_root = addon_dir / "static" / "tests"
        if not tests_root.is_dir():
            continue
        target = tests_root / rel if rel else tests_root
        if target.is_dir():
            return sorted(target.rglob("*.test.js"))
        leaf = target.with_name(target.name + ".test.js")
        if leaf.is_file():
            return [leaf]
    return []


def child_suites(suite: str) -> list[str]:

    addon, _, rel = suite.lstrip("@").partition("/")
    for addon_dir in iter_addon_dirs():
        if addon_dir.name != addon:
            continue
        tests_root = addon_dir / "static" / "tests"
        target = tests_root / rel if rel else tests_root
        if not target.is_dir():
            return []
        children = []
        for entry in sorted(target.iterdir()):
            if entry.is_dir() and any(entry.rglob("*.test.js")):
                children.append(f"{suite}/{entry.name}")
            elif entry.name.endswith(".test.js"):
                children.append(f"{suite}/{entry.name[: -len('.test.js')]}")
        return children
    return []


def _imports_of(path: Path, probe: re.Pattern[str] | None = None) -> set[str]:

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    if probe is not None and not probe.search(text):
        return set()
    own = file_to_specifier(path)
    base = own.rsplit("/", 1)[0] if own else None
    specs: set[str] = set()
    for spec, _lineno in collect_imports(text):
        if spec.startswith("@"):
            specs.add(spec)
        elif spec.startswith(".") and base:
            resolved = posixpath.normpath(f"{base}/{spec}")
            if resolved.startswith("@"):
                specs.add(re.sub(r"\.js$", "", resolved))
    return specs


def _specifier_probe(specs: set[str]) -> re.Pattern[str] | None:

    if not specs:
        return None
    wanted = specs | {spec.rsplit("/", 1)[-1] for spec in specs}
    return re.compile("|".join(re.escape(spec) for spec in sorted(wanted)))


def _git_toplevels() -> list[Path]:
    tops: list[Path] = []
    for root in ADDONS_ROOTS:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        top = Path(out.stdout.strip()) if out.returncode == 0 else None
        if top and top not in tops:
            tops.append(top)
    return tops


def changed_web_js(paths: list[str] | None = None) -> list[Path]:

    if paths:
        return [Path(p).resolve() for p in paths]
    changed: list[Path] = []
    seen: set[Path] = set()
    for top in _git_toplevels():
        for argv in (
            ["diff", "--name-only", "-z", "HEAD"],
            ["ls-files", "--others", "--exclude-standard", "-z"],
        ):
            out = subprocess.run(
                ["git", "-C", str(top), *argv],
                capture_output=True,
                text=True,
                check=False,
            )
            for name in out.stdout.split("\0"):
                if not (name.endswith(".js") and "/static/" in name):
                    continue
                resolved = (top / name).resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    changed.append(resolved)
    return changed


def affected_suites(changed: list[Path], *, downstream: bool = False) -> list[str]:

    changed_specs: set[str] = set()
    suites: set[str] = set()
    changed_addons: set[str] = set()
    for path in changed:
        spec = file_to_specifier(path)
        if spec is None:
            continue
        changed_addons.add(spec.lstrip("@").partition("/")[0])
        if path.name.endswith(".test.js"):
            suite = specifier_to_suite(spec)
            if suite:
                suites.add(suite)
        else:
            changed_specs.add(spec)

    def keep(names: set[str]) -> list[str]:
        if downstream:
            return sorted(names)
        return sorted(
            n for n in names if n.lstrip("@").partition("/")[0] in changed_addons
        )

    if not changed_specs:
        return keep(suites)

    hop_specs: set[str] = set()
    changed_probe = _specifier_probe(changed_specs)
    for src in _iter_src_files():
        if _imports_of(src, changed_probe) & changed_specs:
            spec = file_to_specifier(src)
            if spec:
                hop_specs.add(spec)
    target_specs = changed_specs | hop_specs

    target_probe = _specifier_probe(target_specs)
    for test_file in _iter_test_files():
        if _imports_of(test_file, target_probe) & target_specs:
            spec = file_to_specifier(test_file)
            suite = specifier_to_suite(spec) if spec else None
            if suite:
                suites.add(suite)
    return keep(suites)
