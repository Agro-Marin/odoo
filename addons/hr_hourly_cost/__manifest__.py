{
    "name": "Employee Hourly Wage",
    "version": "1.0",
    "category": "Services/Timesheets",
    "summary": "Employee Hourly Wage",
    "description": """
This module assigns an hourly wage to employees to be used by other modules.
============================================================================

    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "hr",
    ],
    "data": [
        "views/hr_employee_views.xml",
    ],
    "demo": [
        "demo/hr_hourly_cost_demo.xml",
    ],
}
