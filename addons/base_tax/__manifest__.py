{
    "name": "Tax Computation Engine",
    "version": "19.0.1.0.0",
    "category": "Hidden",
    "summary": "Standalone tax computation for order types",
    "description": """
Tax Computation Engine
=======================

Canonical tax computation engine defining ``account.tax``, ``account.tax.group``,
and ``account.tax.repartition.line``.  The ``account`` module inherits from these
models (via ``_inherit``) to add accounting-specific fields and methods such as
journal accounts, tax tags, exigibility, and CABA handling.

Modules that need tax computation without the full accounting stack (e.g.
``base_order``, ``sale``, ``purchase``) can depend on ``base_tax`` directly.

Models:
-------
* **account.tax** — tax definition, rate computation, base line preparation
* **account.tax.group** — tax grouping for display and reporting
* **account.tax.repartition.line** — tax distribution factors

Key API:
--------
* ``_prepare_base_line_for_taxes_computation()`` — convert record → base_line dict
* ``_add_tax_details_in_base_lines()`` — compute tax amounts
* ``_round_base_lines_tax_details()`` — rounding pipeline
* ``_get_tax_totals_summary()`` — aggregate into display dict
* ``compute_all()`` — public tax computation API
    """,
    "author": "Odoo Community",
    "website": "https://www.odoo.com",
    "license": "LGPL-3",
    "depends": [
        "product",
    ],
    "data": [
        "security/ir.model.access.csv",
    ],
    "assets": {
        # The JS mirror of the tax engine (kept consistent with
        # models/account_tax.py). It used to live in ``account`` and is still
        # imported as ``@account/helpers/account_tax`` via a re-export shim there;
        # PoS and pos_self_order pull it into their own bundles explicitly.
        "web.assets_backend": [
            "base_tax/static/src/helpers/*.js",
        ],
        "web.assets_frontend": [
            "base_tax/static/src/helpers/*.js",
        ],
    },
}
