"""Shared location/artifact helpers for the test framework.

Home of the pieces needed by both :mod:`odoo.tests.common` and
:mod:`odoo.tests.browser` — a separate module so the browser layer does not
have to import the (much heavier) ``common`` at runtime.
"""

import logging
import os
import pathlib
import re
import sys
import threading
from datetime import datetime

import odoo.tools

_logger = logging.getLogger(__name__)

# The odoo library is supposed already configured.
HOST = "127.0.0.1"


def env_int(varname: str, default: int) -> int:
    """Parse an integer environment variable, tolerating empty-but-set values.

    CI environments commonly export variables with an empty value; a bare
    ``int(os.environ.get(var, "0"))`` then dies with ``ValueError`` — at import
    time when the result feeds a class attribute, taking the whole framework
    down with it.  Unset and empty both mean ``default``; anything else must
    parse as an int.
    """
    raw = os.environ.get(varname, "")
    return int(raw) if raw.strip() else default


def get_db_name() -> str:
    """Return the configured test database name."""
    dbnames = odoo.tools.config["db_name"]
    # If the database name is not provided on the command-line,
    # use the one on the thread (which means if it is provided on
    # the command-line, this will break when installing another
    # database from XML-RPC).
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
    """Save a test artifact (screenshot, screencast frame, etc.) to disk."""
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
