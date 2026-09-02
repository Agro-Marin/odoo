{
    "name": "Purchase Repair",
    "version": "1.0",
    "category": "Supply Chain/Purchase",
    "summary": "Keep track of linked purchase and repair orders",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "repair",
        "purchase_stock",
    ],
    "data": [
        "views/purchase_views.xml",
        "views/repair_views.xml",
    ],
    "installable": True,
    "auto_install": True,
}
