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
        "wizards/confirm_expiry_view.xml",
    ],
    "auto_install": True,
}
