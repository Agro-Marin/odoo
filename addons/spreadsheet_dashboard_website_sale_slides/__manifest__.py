{
    "name": "Spreadsheet dashboard for eLearning",
    "version": "1.0",
    "category": "Productivity/Dashboard",
    "summary": "Spreadsheet",
    "description": "Spreadsheet",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "spreadsheet_dashboard",
        "website_sale_slides",
    ],
    "data": [
        "data/dashboards.xml",
    ],
    "installable": True,
    "auto_install": [
        "website_sale_slides",
    ],
}
