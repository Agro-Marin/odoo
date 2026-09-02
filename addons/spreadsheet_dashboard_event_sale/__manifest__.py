{
    "name": "Spreadsheet dashboard for events",
    "version": "1.0",
    "category": "Productivity/Dashboard",
    "summary": "Spreadsheet",
    "description": "Spreadsheet",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "spreadsheet_dashboard",
        "event_sale",
    ],
    "data": [
        "data/dashboards.xml",
    ],
    "installable": True,
    "auto_install": [
        "event_sale",
    ],
}
