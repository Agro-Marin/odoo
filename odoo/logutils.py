"""Logging infrastructure for the Odoo server.

Provides the log handlers (file, PostgreSQL), formatters (colored console,
JSON), performance filters, and the ``init_logger`` setup.
"""

import contextlib
import json
import logging
import logging.config
import logging.handlers
import os
import platform
import sys
import threading
import traceback
import warnings
from pathlib import Path
from typing import IO, TYPE_CHECKING, Final

import werkzeug.serving

from . import db, release, tools
from .libs.json import dumps as json_dumps

if TYPE_CHECKING:
    import types

_logger = logging.getLogger(__name__)


class WatchedFileHandler(logging.handlers.WatchedFileHandler):
    def __init__(self, filename: str) -> None:
        self.errors = None  # py38
        super().__init__(filename)
        # Unfix bpo-26789, in case the fix is present
        self._builtin_open = None

    def _open(self) -> IO[str]:
        return Path(self.baseFilename).open(
            self.mode, encoding=self.encoding, errors=self.errors
        )


class PostgreSQLHandler(logging.Handler):
    """PostgreSQL Logging Handler will store logs in the database, by default
    the current database, can be set using --log-db=DBNAME
    """

    def __init__(self) -> None:
        super().__init__()
        self._support_metadata: bool = False
        if tools.config["log_db"] != "%d":
            with (
                contextlib.suppress(Exception),
                tools.mute_logger("odoo.db"),
                db.db_connect(tools.config["log_db"], allow_uri=True).cursor() as cr,
            ):
                self._support_metadata = bool(
                    tools.sql.column_exists(cr, "ir_logging", "metadata")
                )

    def emit(self, record: logging.LogRecord) -> None:
        ct = threading.current_thread()
        ct_db = getattr(ct, "dbname", None)
        dbname = (
            tools.config["log_db"]
            if tools.config["log_db"] and tools.config["log_db"] != "%d"
            else ct_db
        )
        if not dbname:
            return
        with (
            contextlib.suppress(Exception),
            tools.mute_logger("odoo.db"),
            db.db_connect(dbname, allow_uri=True).cursor() as cr,
        ):
            # preclude risks of deadlocks
            cr.execute("SET LOCAL statement_timeout = 1000")
            msg = str(record.msg)
            if record.args:
                msg = msg % record.args
            traceback = getattr(record, "exc_text", "")
            if traceback:
                msg = f"{msg}\n{traceback}"
            # we do not use record.levelname because it may have been changed by ColoredFormatter.
            levelname = logging.getLevelName(record.levelno)

            val = (
                "server",
                ct_db,
                record.name,
                levelname,
                msg,
                record.pathname,
                record.lineno,
                record.funcName,
            )

            if self._support_metadata:
                from . import modules

                metadata = {}
                if modules.module.current_test:
                    with contextlib.suppress(Exception):
                        metadata["test"] = (
                            modules.module.current_test.get_log_metadata()
                        )

                if metadata:
                    cr.execute(
                        """
                        INSERT INTO ir_logging(create_date, type, dbname, name, level, message, path, line, func, metadata)
                        VALUES (NOW() at time zone 'UTC', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                        (*val, json_dumps(metadata)),
                    )
                    return

            cr.execute(
                """
                INSERT INTO ir_logging(create_date, type, dbname, name, level, message, path, line, func)
                VALUES (NOW() at time zone 'UTC', %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                val,
            )


BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE, _NOTHING, DEFAULT = range(10)
# The background is set with 40 plus the number of the color, and the foreground with 30
# These are the sequences needed to get colored output
RESET_SEQ: Final[str] = "\033[0m"
COLOR_SEQ: Final[str] = "\033[1;%dm"
BOLD_SEQ: Final[str] = "\033[1m"
COLOR_PATTERN: Final[str] = f"{COLOR_SEQ}{COLOR_SEQ}%s{RESET_SEQ}"
LEVEL_COLOR_MAPPING: Final[dict[int, tuple[int, int]]] = {
    logging.DEBUG: (BLUE, DEFAULT),
    logging.INFO: (GREEN, DEFAULT),
    logging.WARNING: (YELLOW, DEFAULT),
    logging.ERROR: (RED, DEFAULT),
    logging.CRITICAL: (WHITE, RED),
}


class PerfFilter(logging.Filter):
    def format_perf(
        self, query_count: int, query_time: float, remaining_time: float
    ) -> tuple[str, str, str]:
        return (
            f"{query_count:d}",
            f"{query_time:.3f}",
            f"{remaining_time:.3f}",
        )

    def format_cursor_mode(self, cursor_mode: str | None) -> str:
        return cursor_mode or "-"

    def filter(self, record: logging.LogRecord) -> bool:
        if hasattr(threading.current_thread(), "query_count"):
            query_count = threading.current_thread().query_count
            query_time = threading.current_thread().query_time
            perf_t0 = threading.current_thread().perf_t0
            remaining_time = tools.real_time() - perf_t0 - query_time
            record.perf_info = "%s %s %s" % self.format_perf(
                query_count, query_time, remaining_time
            )
            if tools.config["db_replica_host"] or "replica" in tools.config["dev_mode"]:
                cursor_mode = threading.current_thread().cursor_mode
                record.perf_info = (
                    f"{record.perf_info} {self.format_cursor_mode(cursor_mode)}"
                )
            delattr(threading.current_thread(), "query_count")
        elif tools.config["db_replica_host"] or "replica" in tools.config["dev_mode"]:
            # replica mode carries a 4th (cursor-mode) placeholder column
            record.perf_info = "- - - -"
        else:
            record.perf_info = "- - -"
        return True


class ColoredPerfFilter(PerfFilter):
    def format_perf(
        self, query_count: int, query_time: float, remaining_time: float
    ) -> tuple[str, str, str]:
        def colorize_time(time, format, low=1, high=5):
            if time > high:
                return COLOR_PATTERN % (30 + RED, 40 + DEFAULT, format % time)
            if time > low:
                return COLOR_PATTERN % (
                    30 + YELLOW,
                    40 + DEFAULT,
                    format % time,
                )
            return format % time

        return (
            colorize_time(query_count, "%d", 100, 1000),
            colorize_time(query_time, "%.3f", 0.1, 3),
            colorize_time(remaining_time, "%.3f", 1, 5),
        )

    def format_cursor_mode(self, cursor_mode: str | None) -> str:
        cursor_mode = super().format_cursor_mode(cursor_mode)
        cursor_mode_color = (
            RED if cursor_mode == "ro->rw" else YELLOW if cursor_mode == "rw" else GREEN
        )
        return COLOR_PATTERN % (
            30 + cursor_mode_color,
            40 + DEFAULT,
            cursor_mode,
        )


class ColoredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fg_color, bg_color = LEVEL_COLOR_MAPPING.get(record.levelno, (GREEN, DEFAULT))
        record.levelname = COLOR_PATTERN % (
            30 + fg_color,
            40 + bg_color,
            record.levelname,
        )
        return super().format(record)


class JSONFormatter(logging.Formatter):
    """Format log records as JSON, for structured/ingestible logs.

    Reference it from a ``--log-config`` dictConfig as a handler's formatter,
    e.g. ``{"()": "odoo.logutils.JSONFormatter"}``.
    """

    def __init__(
        self, *args, record_keys=None, ignore_record_keys=None, **kwargs
    ) -> None:
        super().__init__(*args, **kwargs)
        self.record_keys = record_keys
        if ignore_record_keys is not None:
            self.ignore_record_keys = set(ignore_record_keys)
        else:
            # drop keys derived from others; keep the formatted 'message'
            # since msg/args can't be reformatted once JSON-serialized
            self.ignore_record_keys = {
                "msecs",  # derived from created
                "relativeCreated",  # derived from created
                "asctime",  # derived from created
                "filename",  # derived from pathname
                "module",  # derived from filename (pathname)
                "msg",  # formatted in message
                "args",  # formatted in message
            }

    def format(self, record: logging.LogRecord) -> str:
        record_json = {}
        record_keys = self.record_keys
        if record_keys is None:
            record_keys = self._get_default_record_keys(record)
        for key in record_keys:
            if key == "exc_info":
                if record.exc_info:
                    if not record.exc_text:
                        record.exc_text = self.formatException(record.exc_info)
                    record_json[key] = record.exc_text
            elif key == "stack_info":
                if record.stack_info:
                    record_json[key] = self.formatStack(record.stack_info)
            elif key == "message":
                record.message = record.getMessage()
                record_json[key] = record.message
            elif key == "asctime":
                record.asctime = self.formatTime(record, self.datefmt)
                record_json[key] = record.asctime
            elif key == "test":
                from .modules import module

                if module.current_test:
                    with contextlib.suppress(Exception):
                        record_json[key] = module.current_test.get_log_metadata()
            else:
                value = getattr(record, key, None)
                if value is not None:
                    record_json[key] = value

        return json.dumps(record_json, default=str)

    def _get_default_record_keys(self, record: logging.LogRecord) -> list:
        # parenthesised so '-' applies after '|'; the unparenthesised upstream
        # form binds '-' first and leaves the ignored keys in the output
        return list((record.__dict__.keys() | {"message"}) - self.ignore_record_keys)


class LogRecord(logging.LogRecord):
    def __init__(
        self,
        name: str,
        level: int,
        pathname: str,
        lineno: int,
        msg: object,
        args: tuple | dict[str, object] | None,
        exc_info: tuple[type[BaseException], BaseException, types.TracebackType]
        | tuple[None, None, None]
        | bool
        | None,
        func: str | None = None,
        sinfo: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(
            name,
            level,
            pathname,
            lineno,
            msg,
            args,
            exc_info,
            func=func,
            sinfo=sinfo,
            **kwargs,
        )
        self.perf_info = ""
        self.pid = os.getpid()
        self.dbname = getattr(threading.current_thread(), "dbname", "?")
        uid = getattr(threading.current_thread(), "uid", None)
        self.uid = uid if uid is not None else "-"


showwarning: object = None


def init_logger() -> None:
    global showwarning  # noqa: PLW0603
    if logging.getLogRecordFactory() is LogRecord:
        return

    logging.setLogRecordFactory(LogRecord)

    logging.captureWarnings(True)
    # after logging.captureWarnings so we override its hook, not the reverse
    showwarning = warnings.showwarning
    warnings.showwarning = showwarning_with_traceback

    # enable deprecation warnings (disabled by default)
    warnings.simplefilter("default", category=DeprecationWarning)
    # https://github.com/urllib3/urllib3/issues/2680
    warnings.filterwarnings(
        "ignore",
        r"^\'urllib3.contrib.pyopenssl\' module is deprecated.+",
        category=DeprecationWarning,
    )
    # ignore a bunch of warnings we can't really fix ourselves
    for module in [
        "babel.util",  # deprecated parser module, no release yet
        "zeep.loader",  # zeep using defusedxml.lxml
        "ofxparse",  # ofxparse importing ABC from collections
        "astroid",  # deprecated imp module (fixed in 2.5.1)
        "requests_toolbelt",  # importing ABC from collections (fixed in 0.9)
    ]:
        warnings.filterwarnings("ignore", category=DeprecationWarning, module=module)

    # rsjmin triggers this with Python 3.10+ (that warning comes from the C code and has no `module`)
    warnings.filterwarnings(
        "ignore",
        r"^PyUnicode_FromUnicode\(NULL, size\) is deprecated",
        category=DeprecationWarning,
    )
    # the SVG guesser thing always compares str and bytes, ignore it
    warnings.filterwarnings("ignore", category=BytesWarning, module="odoo.tools.image")

    # need to be adapted later but too muchwork for this pr.
    warnings.filterwarnings(
        "ignore",
        r"^datetime.datetime.utcnow\(\) is deprecated and scheduled for removal in a future version.*",
        category=DeprecationWarning,
    )

    # pkg_ressouce is used in google-auth < 1.23.0 (removed in https://github.com/googleapis/google-auth-library-python/pull/596)
    # unfortunately, in ubuntu jammy and noble, the google-auth version is 1.5.1
    # starting from noble, the default pkg_ressource version emits a warning on import, triggered when importing
    # google-auth
    warnings.filterwarnings(
        "ignore",
        r"pkg_resources is deprecated as an API.+",
        category=DeprecationWarning,
    )
    warnings.filterwarnings(
        "ignore",
        r"Deprecated call to \`pkg_resources.declare_namespace.+",
        category=DeprecationWarning,
    )

    # This warning is triggered library only during the python precompilation which does not occur on readonly filesystem
    warnings.filterwarnings(
        "ignore",
        r"invalid escape sequence",
        category=DeprecationWarning,
        module=".*vobject",
    )
    warnings.filterwarnings(
        "ignore",
        r"invalid escape sequence",
        category=SyntaxWarning,
        module=".*vobject",
    )
    from .tools.translate import resetlocale

    resetlocale()

    log_config = tools.config["log_config"]
    if log_config:
        with Path(log_config).open("rb") as fobj:
            conf = json.load(fobj)
            # loggers are created at import time; disabling existing loggers
            # would silence everything created before this config is loaded
            conf["disable_existing_loggers"] = False
        logging.config.dictConfig(conf)
        # unless the config opts back in, its handlers fully replace Odoo's
        if not conf.get("keep_odoo_default", False):
            return

    # create a format for log messages and dates
    format = "%(asctime)s %(pid)s %(levelname)s uid:%(uid)s %(dbname)s %(name)s: %(message)s %(perf_info)s"
    # Normal Handler on stderr
    handler = logging.StreamHandler()

    if tools.config["syslog"]:
        # SysLog Handler
        if os.name == "nt":
            handler = logging.handlers.NTEventLogHandler(
                f"{release.description} {release.version}"
            )
        elif platform.system() == "Darwin":
            handler = logging.handlers.SysLogHandler("/var/run/log")
        else:
            handler = logging.handlers.SysLogHandler("/dev/log")
        format = f"{release.description} {release.version}:%(dbname)s:%(levelname)s:%(name)s:%(message)s"

    elif tools.config["logfile"]:
        # LogFile Handler
        logf = tools.config["logfile"]
        try:
            # We check we have the right location for the log files
            logpath = Path(logf)
            logpath.parent.mkdir(parents=True, exist_ok=True)
            if os.name == "posix":
                handler = WatchedFileHandler(logf)
            else:
                handler = logging.FileHandler(logf)
        except Exception:
            sys.stderr.write(
                "ERROR: couldn't create the logfile directory. Logging to the standard output.\n"
            )

    # Check that handler.stream has a fileno() method: when running Odoo
    # behind Apache with mod_wsgi, handler.stream will have type mod_wsgi.Log,
    # which has no fileno() method. (mod_wsgi.Log is what is being bound to
    # sys.stderr when the logging.StreamHandler is being constructed above.)
    def is_a_tty(stream):
        return hasattr(stream, "fileno") and os.isatty(stream.fileno())

    if (
        os.name == "posix"
        and isinstance(handler, logging.StreamHandler)
        and (is_a_tty(handler.stream) or os.environ.get("ODOO_PY_COLORS"))
    ):
        formatter = ColoredFormatter(format)
        perf_filter = ColoredPerfFilter()
    else:
        formatter = logging.Formatter(format)
        perf_filter = PerfFilter()
        werkzeug.serving._log_add_style = False
    handler.setFormatter(formatter)
    logging.getLogger().addHandler(handler)
    logging.getLogger("werkzeug").addFilter(perf_filter)

    if tools.config["log_db"]:
        db_levels = {
            "debug": logging.DEBUG,
            "info": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
            "critical": logging.CRITICAL,
        }
        postgresqlHandler = PostgreSQLHandler()
        postgresqlHandler.setLevel(
            int(
                db_levels.get(
                    tools.config["log_db_level"], tools.config["log_db_level"]
                )
            )
        )
        logging.getLogger().addHandler(postgresqlHandler)

    # Configure loggers levels
    pseudo_config = PSEUDOCONFIG_MAPPER.get(tools.config["log_level"], [])

    logconfig = tools.config["log_handler"]

    logging_configurations = DEFAULT_LOG_CONFIGURATION + pseudo_config + logconfig
    for logconfig_item in logging_configurations:
        loggername, level = logconfig_item.strip().split(":")
        level = getattr(logging, level, logging.INFO)
        logger = logging.getLogger(loggername)
        logger.setLevel(level)

    for logconfig_item in logging_configurations:
        _logger.debug('logger level set: "%s"', logconfig_item)


DEFAULT_LOG_CONFIGURATION: Final[list[str]] = [
    "odoo.http.rpc.request:INFO",
    "odoo.http.rpc.response:INFO",
    "fontTools:WARNING",
    ":INFO",
]
PSEUDOCONFIG_MAPPER: Final[dict[str, list[str]]] = {
    "debug_rpc_answer": ["odoo:DEBUG", "odoo.db:INFO", "odoo.http.rpc:DEBUG"],
    "debug_rpc": ["odoo:DEBUG", "odoo.db:INFO", "odoo.http.rpc.request:DEBUG"],
    "debug": ["odoo:DEBUG", "odoo.db:INFO"],
    "debug_sql": ["odoo.db:DEBUG"],
    "info": [],
    "runbot": ["odoo:RUNBOT", "werkzeug:WARNING"],
    "warn": ["odoo:WARNING", "werkzeug:WARNING"],
    "error": ["odoo:ERROR", "werkzeug:ERROR"],
    "critical": ["odoo:CRITICAL", "werkzeug:CRITICAL"],
}

logging.RUNBOT = 25
logging.addLevelName(logging.RUNBOT, "INFO")  # displayed as info in log
# addLevelName also remaps name->level ("INFO" -> 25), which would break stdlib
# lookups by name (assertLogs(level="INFO"), setLevel("INFO")) into filtering out
# real INFO (20) records. Restore the canonical name->level entry; the display
# alias above stays. ("odoo:RUNBOT" specs resolve via the module attribute.)
logging._nameToLevel["INFO"] = logging.INFO
IGNORE: Final[frozenset[str]] = frozenset(
    {
        "Comparison between bytes and int",  # a.foo != False or some shit, we don't care
    }
)


def showwarning_with_traceback(
    message: Warning,
    category: type[Warning],
    filename: str,
    lineno: int,
    file: IO[str] | None = None,
    line: str | None = None,
) -> None:
    if category is BytesWarning and message.args[0] in IGNORE:
        return None

    # find the stack frame matching (filename, lineno)
    filtered = []
    for frame in traceback.extract_stack():
        if frame.name == "__call__" and frame.filename.endswith("/odoo/http.py"):
            # we don't care about the frames above our wsgi entrypoint
            filtered.clear()
        if "importlib" not in frame.filename:
            filtered.append(frame)
        if frame.filename == filename and frame.lineno == lineno:
            break
    return showwarning(
        message,
        category,
        filename,
        lineno,
        file=file,
        line="".join(traceback.format_list(filtered)),
    )


def runbot(self: logging.Logger, message: str, *args: object, **kws: object) -> None:
    self.log(logging.RUNBOT, message, *args, **kws)


logging.Logger.runbot = runbot
