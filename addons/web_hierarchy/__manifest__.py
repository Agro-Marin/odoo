{
    "name": "Web Hierarchy",
    "version": "1.0",
    "category": "Hidden",
    "description": """
Odoo Web Hierarchy view
=======================

This module adds a new view called to be able to define a view to display
an organization such as an Organization Chart for employees for instance.
        """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "web",
    ],
    "assets": {
        "web.assets_backend": [
            "web_hierarchy/static/src/**/*",
        ],
        "web.assets_unit_tests": [
            "web_hierarchy/static/tests/**/*",
        ],
    },
}
