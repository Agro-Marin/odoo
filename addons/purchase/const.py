ORDER_STATE = [
    ("draft", "RFQ"),
    ("done", "Purchase Order"),
    ("cancel", "Cancelled"),
]

INVOICE_STATE = [
    ("no", "Nothing to invoice"),
    ("to do", "To invoice"),
    ("partial", "Partially invoiced"),
    ("done", "Fully invoiced"),
    ("over done", "Over-invoiced"),
]

INVOICE_STATE_PRIORITY = ["over done", "to do", "partial", "done", "no"]


ONE_DAY_SECONDS = 86400

DATE_MATCH_THRESHOLD_SECONDS = ONE_DAY_SECONDS


MAX_PRODUCTS_IN_MESSAGE = 50

MAX_SUPPLIERS_PER_PRODUCT = 10


BILLING_MATCH_TOLERANCE = 0.02
