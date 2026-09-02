{
    "name": "Spreadsheet Accounting Formulas",
    "version": "1.0",
    "category": "Accounting",
    "summary": "Spreadsheet Accounting formulas",
    "description": "Spreadsheet Accounting formulas",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "spreadsheet",
        "account",
    ],
    "assets": {
        "spreadsheet.o_spreadsheet": [
            (
                "after",
                "spreadsheet/static/src/o_spreadsheet/o_spreadsheet.js",
                "spreadsheet_account/static/src/**/*.js",
            ),
        ],
        "web.assets_unit_tests": [
            "spreadsheet_account/static/tests/**/*",
        ],
    },
    "installable": True,
    "auto_install": True,
}
