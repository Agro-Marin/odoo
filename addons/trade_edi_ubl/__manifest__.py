{
    "name": "Trade UBL Ordering",
    "version": "19.0.1.0.0",
    "category": "Hidden",
    "summary": "UBL BIS Ordering 3 export and import for orders, in either direction",
    "description": """
Trade UBL Ordering
==================

Bridge module connecting ``trade_account`` with ``account_edi_ubl_cii``: the
Peppol BIS Ordering 3 document of an order, written once for both directions.

* **trade.edi.xml.ubl_bis3** — builds the Order document of a sales or
  purchase order and imports one into an order. Which party is the company,
  the partner's import role and the tax type follow the order's direction;
  a concrete builder names its order type code, reference field and nodes,
  and delivery-address field.
* **mixin.order** — offers the order's builder to the EDI report and routes
  an uploaded Order document to it.
    """,
    "author": "Odoo Community",
    "website": "https://www.odoo.com",
    "license": "LGPL-3",
    "depends": [
        "trade_account",
        "account_edi_ubl_cii",
    ],
    "auto_install": True,
}
