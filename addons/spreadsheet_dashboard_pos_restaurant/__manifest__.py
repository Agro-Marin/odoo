{
    "name": "Spreadsheet dashboard for restaurants",
    "version": "1.0",
    "category": "Productivity/Dashboard",
    "summary": "Spreadsheet",
    "description": "Spreadsheet",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "spreadsheet_dashboard",
        "pos_hr",
        "pos_restaurant",
    ],
    "data": [
        "data/dashboards.xml",
    ],
    "installable": True,
    "auto_install": [
        "pos_hr",
        "pos_restaurant",
    ],
}
