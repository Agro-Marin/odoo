import atexit
import contextlib
import logging
import os
import sys
from pathlib import Path

from psycopg.errors import InsufficientPrivilege

import odoo
import odoo.release  # noqa: F401  binds the submodule so `odoo.release.version` resolves below
from odoo.service import db, server
from odoo.tools import config

from . import Command
from .command import check_db_not_maintenance

_logger = logging.getLogger("odoo")


def warn_running_as_root() -> None:
    if os.name == "posix" and os.getuid() == 0:
        sys.stderr.write("Running as user 'root' is a security risk.\n")


def check_db_user_not_postgres() -> None:
    if (config["db_user"] or os.environ.get("PGUSER")) == "postgres":
        sys.stderr.write(
            "Using the database user 'postgres' is a security risk, aborting.\n"
        )
        sys.exit(1)


def report_configuration() -> None:
    import odoo.addons

    _logger.info("Odoo version %s", odoo.release.version)
    if Path(config["config"]).is_file():
        _logger.info("Using configuration file at %s", config["config"])
    _logger.info("addons paths: %s", odoo.addons.__path__)
    if config.get("upgrade_path"):
        _logger.info("upgrade path: %s", config["upgrade_path"])
    if config.get("pre_upgrade_scripts"):
        _logger.info("extra upgrade scripts: %s", config["pre_upgrade_scripts"])
    host = config["db_host"] or os.environ.get("PGHOST", "default")
    port = config["db_port"] or os.environ.get("PGPORT", "default")
    user = config["db_user"] or os.environ.get("PGUSER", "default")
    _logger.info("database: %s@%s:%s", user, host, port)
    replica_host = config["db_replica_host"]
    replica_port = config["db_replica_port"]
    if replica_host or replica_port or "replica" in config["dev_mode"]:
        _logger.info(
            "replica database: %s@%s:%s",
            user,
            replica_host or "default",
            replica_port or "default",
        )
    if sys.version_info[:2] > odoo.release.MAX_PY_VERSION:
        _logger.warning(
            "Python %s is not officially supported, please use Python %s instead",
            ".".join(map(str, sys.version_info[:2])),
            ".".join(map(str, odoo.release.MAX_PY_VERSION)),
        )


def remove_pid_file(main_pid: int) -> None:
    if config["pidfile"] and main_pid == os.getpid():
        with contextlib.suppress(OSError):
            Path(config["pidfile"]).unlink()


def write_pid_file() -> None:
    if not odoo.evented and config["pidfile"]:
        pid = os.getpid()
        Path(config["pidfile"]).write_text(str(pid), encoding="utf-8")
        atexit.register(remove_pid_file, pid)


def run_server(args: list[str]) -> None:
    warn_running_as_root()
    config.parse_config(args, setup_logging=True)
    check_db_user_not_postgres()
    report_configuration()

    for db_name in config["db_name"]:
        check_db_not_maintenance(
            db_name,
            error_handler=lambda msg: sys.exit(
                f"{msg} Choose another with -d/--database, or db_name in the "
                "config file."
            ),
        )

    for db_name in config["db_name"]:
        try:
            db._create_empty_database(db_name)
            config["init"]["base"] = True
        except InsufficientPrivilege as err:
            _logger.info(
                "Could not determine if database %s exists, skipping auto-creation: %s",
                db_name,
                err,
            )
        except db.DatabaseExists:
            pass
        except Exception as err:
            sys.exit(f"Could not create database {db_name!r}. ({err})")

    stop = config["stop_after_init"]

    write_pid_file()
    rc = server.start(preload=config["db_name"], stop=stop)
    sys.exit(rc)


class Server(Command):
    description = "Start the odoo server (default command)"

    def run(self, args: list[str]) -> None:
        config.parser.prog = self.prog
        run_server(args)
