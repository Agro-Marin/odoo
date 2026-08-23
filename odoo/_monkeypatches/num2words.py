import logging

_logger = logging.getLogger(__name__)


def patch_module() -> None:
    """Register Bulgarian, which upstream num2words 0.5.14 does not carry.

    The converter itself is `odoo.libs.locale.BulgarianNumerals` -- a language
    implementation, not a patch, and it lived here only because a third-party
    registry is its one integration point. `CONVERTER_CLASSES` holds instances
    despite its name; that is upstream's shape, not ours.
    """
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
