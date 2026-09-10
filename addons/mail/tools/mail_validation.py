import logging

from odoo import tools

_logger = logging.getLogger(__name__)

_flanker_lib_warning = False

try:
    from flanker.addresslib import address

    logging.getLogger("flanker.addresslib.validate").setLevel(logging.ERROR)

    def is_valid_email(email: str) -> bool:
        return bool(address.validate_address(email))

except ImportError:

    def is_valid_email(email: str) -> bool:
        global _flanker_lib_warning  # noqa: PLW0603 - one-shot latch so the missing-flanker warning is logged once per process
        if not _flanker_lib_warning:
            _flanker_lib_warning = True
            _logger.info(
                "The (optional) `flanker` Python module is not installed,"
                "so email validation will fallback to email_normalize."
            )
        return bool(tools.email_normalize(email))
