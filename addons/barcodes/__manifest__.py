{
    "name": "Barcode",
    "version": "2.0",
    "category": "Supply Chain/Inventory",
    "summary": "Scan and Parse Barcodes",
    "depends": ["web"],
    "data": [
        "security/ir.model.access.csv",
        "data/barcodes_data.xml",
        "views/barcodes_view.xml",
    ],
    "installable": True,
    "post_init_hook": "_assign_default_nomenclature",
    "assets": {
        "web.assets_backend": [
            "barcodes/static/src/**/*",
        ],
        "web.assets_unit_tests": [
            "barcodes/static/tests/*.test.js",
            # Golden vectors shared with tests/test_barcode_conformance.py.
            "barcodes/static/tests/conformance_vectors.js",
            "barcodes/static/tests/barcode_test_helpers.js",
        ],
    },
    "author": "Odoo S.A.",
    "license": "LGPL-3",
}
