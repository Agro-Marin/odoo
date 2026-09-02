{
    "name": "HR Org Chart",
    "version": "1.0",
    "category": "Human Resources",
    "description": """
Org Chart Widget for HR
=======================

This module extend the employee form with a organizational chart.
(N+1, N+2, direct subordinates)
        """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "hr",
        "web_hierarchy",
    ],
    "data": [
        "views/hr_department_views.xml",
        "views/hr_employee_public_views.xml",
        "views/hr_views.xml",
    ],
    "assets": {
        "web._assets_primary_variables": [
            "hr_org_chart/static/src/scss/variables.scss",
        ],
        "web.assets_backend": [
            "hr_org_chart/static/src/fields/*",
            "hr_org_chart/static/src/views/**/*",
        ],
        "web.assets_tests": [
            "hr_org_chart/static/tests/tours/*.js",
        ],
        "web.assets_unit_tests": [
            "hr_org_chart/static/tests/**/*",
        ],
    },
    "auto_install": [
        "hr",
    ],
}
