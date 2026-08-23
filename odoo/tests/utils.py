import logging
import os
import pathlib
import re
import sys
import threading
import unittest
from datetime import datetime

import odoo.tools

_logger = logging.getLogger(__name__)

HOST = "127.0.0.1"


class InfrastructureUnavailable(unittest.SkipTest):
    """The environment cannot run this test -- not a judgement that it shouldn't.

    A missing Chrome, an unreachable devtools port and an absent
    websocket-client all used to raise plain SkipTest, so a host with a broken
    browser ran zero tour assertions and still exited 0. This subclasses
    SkipTest, so the default behaviour is unchanged and the test still skips --
    but it is counted apart from deliberate skips, named in the run summary,
    and promoted to an error by ODOO_REQUIRE_INFRA=1.
    """


_TEST_MODULE_PREFIXES = ("odoo.addons.", "odoo.upgrade.")


def addon_relative_path(module_name: str) -> str:
    """``odoo.addons.base.tests.test_x`` -> ``/base/tests/test_x.py``.

    Shared so case.canonical_tag and TagsSelector agree by construction; they
    used to derive this separately, with prefixes differing by a trailing dot.
    """
    for prefix in _TEST_MODULE_PREFIXES:
        module_name = module_name.removeprefix(prefix)
    return f"/{module_name.replace('.', '/')}.py"


def env_int(varname: str, default: int) -> int:
    raw = os.environ.get(varname, "")
    return int(raw) if raw.strip() else default


def get_db_name() -> str:
    dbnames = odoo.tools.config["db_name"]
    if not dbnames and hasattr(threading.current_thread(), "dbname"):
        return threading.current_thread().dbname
    if not dbnames:
        sys.exit("No database name found, please provide one with -d/--database")
    if len(dbnames) > 1:
        sys.exit(
            "-d/--database/db_name has multiple database, please provide a single one"
        )
    return dbnames[0]


def save_test_file(
    test_name: str,
    content: bytes,
    prefix: str,
    extension: str = "png",
    logger: logging.Logger = _logger,
    document_type: str = "Screenshot",
    date_format: str = "%Y%m%d_%H%M%S_%f",
) -> None:
    assert re.fullmatch(r"\w*_", prefix)
    assert re.fullmatch(r"[a-z]+", extension)
    assert re.fullmatch(r"\w+", test_name)
    now = datetime.now().strftime(date_format)
    screenshots_dir = (
        pathlib.Path(odoo.tools.config["screenshots"]) / get_db_name() / "screenshots"
    )
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    full_path = screenshots_dir / f"{prefix}{now}_{test_name}.{extension}"
    full_path.write_bytes(content)
    logger.runbot(f"{document_type} in: {full_path}")
