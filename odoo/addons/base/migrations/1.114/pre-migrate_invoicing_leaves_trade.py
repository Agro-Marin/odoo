from odoo.tools.module_data import adopt_xmlids

MIXINS = ("invoice", "line_invoice", "line_match", "document_match")

OWN_PATTERN = (
    "^(model_mixin_order_(" + "|".join(MIXINS) + ")$"
    "|model_inherit__mixin_order_(" + "|".join(MIXINS) + ")__"
    "|(field|selection|constraint)_{1,2}mixin_order_(" + "|".join(MIXINS) + ")__)"
)

RECORDS = (
    "model_account_move",
    "model_account_move_line",
    "field_account_move_line__is_downpayment",
    "field_account_move_line__id",
    "field_account_move_line__display_name",
    "field_account_move__id",
    "field_account_move__display_name",
)

# trade_stock extended account.move only for the incoterm location, which is
# trade_account's now
TRADE_STOCK_RECORDS = (
    "model_account_move",
    "field_account_move__id",
    "field_account_move__display_name",
)


def migrate(cr, version):
    if not version:
        return
    # before trade loads: an xml id left under trade would be orphaned when
    # trade stops declaring it, and _process_end would delete the record
    # behind it, and for is_downpayment its column
    cr.execute(
        "SELECT name FROM ir_model_data WHERE module = 'trade' AND name ~ %s",
        [OWN_PATTERN],
    )
    owned = [name for (name,) in cr.fetchall()]
    adopt_xmlids(cr, "trade", "trade_account", (*RECORDS, *owned))
    adopt_xmlids(cr, "trade_stock", "trade_account", TRADE_STOCK_RECORDS)
