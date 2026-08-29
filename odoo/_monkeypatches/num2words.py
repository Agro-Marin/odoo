import logging

_logger = logging.getLogger(__name__)


def patch_module() -> None:
    try:
        import num2words
    except ImportError:
        _logger.warning(
            "num2words is not available, Bulgarian number to words conversion "
            "will not work"
        )
        return

    from odoo.libs.locale import BulgarianNumerals

    num2words.CONVERTER_CLASSES["bg"] = BulgarianNumerals()
