{
    "name": "Manufacturing Expiry",
    "version": "1.0",
    "category": "Supply Chain/Manufacturing",
    "summary": "Manufacturing Expiry",
    "description": """
Technical module.
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "mrp",
        "product_expiry",
    ],
    "data": [
        "wizard/confirm_expiry_view.xml",
    ],
    "installable": True,
    "auto_install": True,
}
