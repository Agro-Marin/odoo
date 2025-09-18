# Mapping of config parameters to the crons they toggle.
PARAM_CRON_MAPPING = {
    "sale.async_emails": "sale.send_pending_emails_cron",
    "sale.automatic_invoice": "sale.send_invoice_cron",
}

# Tolerance for price comparison to handle floating point precision issues.
# Used when comparing manual price vs pricelist price.
PRICE_COMPARISON_TOLERANCE = 0.001

# Maximum number of products to list individually in chatter messages.
# Above this threshold, messages will summarize instead of listing each product.
CHATTER_PRODUCT_LIST_THRESHOLD = 50

ORDER_STATE = [
    ("draft", "Quotation"),
    ("done", "Sales Order"),
    ("cancel", "Cancelled"),
]

INVOICE_STATE = [
    ("no", "Nothing to invoice"),
    ("to do", "To invoice"),
    ("partial", "Partially invoiced"),
    ("done", "Fully invoiced"),
    ("over done", "Over-invoiced"),
]
