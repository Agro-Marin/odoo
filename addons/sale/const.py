PARAM_CRON_MAPPING = {
    "sale.async_emails": "sale.send_pending_emails_cron",
    "sale.automatic_invoice": "sale.send_invoice_cron",
}

CHATTER_PRODUCT_LIST_THRESHOLD = 50

ONE_DAY_SECONDS = 86400

DATE_MATCH_THRESHOLD_SECONDS = ONE_DAY_SECONDS

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
