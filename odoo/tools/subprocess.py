import logging
import os
import sys
import threading
import time
import traceback

from odoo.libs.filesystem import which

from .config import config

_logger = logging.getLogger(__name__)


def find_in_path(name: str) -> str:
    path = os.environ.get("PATH", os.defpath).split(os.pathsep)
    if config.get("bin_path") and config["bin_path"] != "None":
        path.append(config["bin_path"])
    return which(name, path=os.pathsep.join(path))


def find_pg_tool(name: str) -> str:
    path = None
    if config["pg_path"] and config["pg_path"] != "None":
        path = config["pg_path"]
    try:
        return which(name, path=path)
    except OSError:
        raise FileNotFoundError(f"Command `{name}` not found.") from None


def exec_pg_environ() -> dict[str, str]:
    env = os.environ.copy()
    if config["db_host"]:
        env["PGHOST"] = config["db_host"]
    if config["db_port"]:
        env["PGPORT"] = str(config["db_port"])
    if config["db_user"]:
        env["PGUSER"] = config["db_user"]
    if config["db_password"]:
        env["PGPASSWORD"] = config["db_password"]
    if config["db_app_name"]:
        env["PGAPPNAME"] = config["db_app_name"].replace("{pid}", f"env{os.getpid()}")[
            :63
        ]
    if config["db_sslmode"]:
        env["PGSSLMODE"] = config["db_sslmode"]
    return env


def stripped_sys_argv(*strip_args: str) -> list[str]:
    strip_args = sorted(
        set(strip_args)
        | {
            "-s",
            "--save",
            "-u",
            "--update",
            "-i",
            "--init",
            "--i18n-overwrite",
        }
    )
    unknown = [s for s in strip_args if not config.parser.has_option(s)]
    if unknown:
        msg = f"Unknown option(s) to strip: {', '.join(unknown)}"
        raise ValueError(msg)
    takes_value = {s: config.parser.get_option(s).takes_value() for s in strip_args}

    longs = tuple(a for a in strip_args if a.startswith("--"))
    shorts = tuple(a for a in strip_args if not a.startswith("--"))
    longs_eq = tuple(l + "=" for l in longs if takes_value[l])

    args = sys.argv[:]

    def strip(args, i):
        return (
            args[i].startswith(shorts)
            or args[i].startswith(longs_eq)
            or (args[i] in longs)
            or (i >= 1 and (args[i - 1] in strip_args) and takes_value[args[i - 1]])
        )

    return [x for i, x in enumerate(args) if not strip(args, i)]


real_time = time.time.__call__


def dumpstacks(
    sig: int | None = None,
    frame: object = None,
    thread_idents: set[int] | None = None,
    log_level: int = logging.INFO,
) -> None:
    code = []

    def extract_stack(stack):
        for filename, lineno, name, line in traceback.extract_stack(stack):
            yield f'File: "{filename}", line {lineno}, in {name}'
            if line:
                yield f"  {line.strip()}"

    threads_info = {
        th.ident: {
            "repr": repr(th),
            "uid": getattr(th, "uid", "n/a"),
            "dbname": getattr(th, "dbname", "n/a"),
            "url": getattr(th, "url", "n/a"),
            "query_count": getattr(th, "query_count", "n/a"),
            "query_time": getattr(th, "query_time", None),
            "perf_t0": getattr(th, "perf_t0", None),
        }
        for th in threading.enumerate()
    }
    for threadId, stack in sys._current_frames().items():
        if not thread_idents or threadId in thread_idents:
            thread_info = threads_info.get(threadId, {})
            query_time = thread_info.get("query_time")
            perf_t0 = thread_info.get("perf_t0")
            remaining_time = None
            if query_time is not None and perf_t0:
                remaining_time = f"{real_time() - perf_t0 - query_time:.3f}"
                query_time = f"{query_time:.3f}"
            repr_ = thread_info.get("repr", threadId)
            dbname = thread_info.get("dbname", "n/a")
            uid = thread_info.get("uid", "n/a")
            url = thread_info.get("url", "n/a")
            qc = thread_info.get("query_count", "n/a")
            qt = query_time or "n/a"
            pt = remaining_time or "n/a"
            code.append(
                f"\n# Thread: {repr_} (db:{dbname}) (uid:{uid}) (url:{url}) (qc:{qc} qt:{qt} pt:{pt})"
            )
            code.extend(extract_stack(stack))

    _logger.log(log_level, "\n".join(code))
