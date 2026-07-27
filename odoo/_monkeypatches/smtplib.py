"""Route smtplib's session debug output to the Odoo logger.

``smtplib`` prints its trace straight to stderr when ``set_debuglevel`` is on,
which bypasses the log configuration and can leak credentials into a stream
nobody filters. Sending it through ``logging`` at DEBUG level keeps it under the
same handlers, levels and formatting as the rest of the server.
"""

import logging
import smtplib
from typing import Any

_logger = logging.getLogger("odoo.addons.base.models.ir_mail_server")


def _print_debug(self: Any, *args: Any) -> None:
    _logger.debug(" ".join(str(a) for a in args))


def patch_module() -> None:
    smtplib.SMTP._print_debug = _print_debug
