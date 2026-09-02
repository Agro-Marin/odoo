{
    "name": "Saudi Arabia - E-invoicing (Simplified)",
    "version": "0.2",
    "category": "Accounting/Localizations/EDI",
    "summary": """
        ZATCA E-Invoicing, support for PoS
    """,
    "description": """
E-invoice implementation for Saudi Arabia; Integration with ZATCA (POS)
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "l10n_sa_pos",
        "l10n_sa_edi",
    ],
    "countries": [
        "sa",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "l10n_sa_edi_pos/static/src/**/*",
        ],
        "web.assets_tests": [
            "l10n_sa_edi_pos/static/tests/tours/**/*",
        ],
    },
}
