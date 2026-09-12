{
    "name": "Spreadsheet dashboard for stock",
    "category": "Productivity/Dashboard",
    "summary": "Spreadsheet",
    "description": "Spreadsheet",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "spreadsheet_dashboard",
        "stock_account",
    ],
    "data": [
        "data/dashboards.xml",
    ],
    "auto_install": [
        "stock_account",
    ],
}
