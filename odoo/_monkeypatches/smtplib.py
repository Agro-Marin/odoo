import logging
import smtplib
from typing import Any

_logger = logging.getLogger("odoo.addons.base.models.ir_mail_server")


def _print_debug(self: Any, *args: Any) -> None:
    _logger.debug(" ".join(str(a) for a in args))


def patch_module() -> None:
    smtplib.SMTP._print_debug = _print_debug
