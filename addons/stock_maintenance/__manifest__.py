{
    "name": "Stock - Maintenance",
    "version": "1.0",
    "category": "Supply Chain/Inventory",
    "summary": "See lots used in maintenance",
    "description": """
Stock in Maintenance
====================
Open the record of the serial number from an equipment form
""",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "stock",
        "maintenance",
    ],
    "data": [
        "views/maintenance_views.xml",
        "views/stock_location.xml",
    ],
    "auto_install": True,
}
