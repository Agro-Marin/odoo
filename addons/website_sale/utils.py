from datetime import UTC

from odoo.http import request


def gmc_format_price(price, currency):
    return f"{currency.round(price)} {currency.name}"


def gmc_format_date(dt):
    return dt.replace(tzinfo=UTC).isoformat(timespec="minutes")


def get_base_unit_price(record, price):
    """Shared by `product.template` and `product.product`: `record` provides its own
    `base_unit_count`, so this cannot be a plain delegation from one model to the other."""
    record.check_singleton()
    return record.base_unit_count and price / record.base_unit_count


def website_show_quick_add(record):
    """Shared by `product.template` and `product.product`: `record` provides its own
    `_get_contextual_price`, so this cannot be a plain delegation from one model to the other."""
    record.check_singleton()
    if not record.filtered_domain(record.env["website"]._product_domain()):
        return False
    return not request.website.prevent_zero_price_sale or record._get_contextual_price()
