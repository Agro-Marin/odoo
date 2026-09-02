{
    "name": "Subcontracting Management with Stock Valuation",
    "version": "0.1",
    "category": "Supply Chain/Manufacturing",
    "description": """
This bridge module allows to manage subcontracting with valuation.
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "mrp_subcontracting",
        "mrp_account",
    ],
    "data": [
        "security/mrp_subcontracting_account_security.xml",
        "security/ir.model.access.csv",
    ],
    "installable": True,
    "auto_install": True,
}
