from odoo.tools.module_data import rename_model, rename_module

MODULES = (
    ("test_base_order_stock", "test_trade_stock"),
    ("test_base_order", "test_trade"),
    ("base_order_stock", "trade_stock"),
    ("base_order", "trade"),
)

# exact names, longest first: rename_model never matches by prefix, the order
# only keeps the log readable
MODELS = (
    (
        "base.order.test.line.price.history.line",
        "test_trade.order.line.price.history.line",
    ),
    ("base.order.test.line.price.history", "test_trade.order.line.price.history"),
    ("base.order.test.document.match", "test_trade.order.document.match"),
    ("base.order.test.line.match", "test_trade.order.line.match"),
    ("base_order_stock.test.order.line", "test_trade_stock.order.line"),
    ("base.order.test.line", "test_trade.order.line"),
    ("base.order.test", "test_trade.order"),
    ("base_order.config", "trade.config"),
)


def migrate(cr, version):
    if not version:
        return
    for old, new in MODULES:
        rename_module(cr, old, new)
    for old, new in MODELS:
        rename_model(cr, old, new)
