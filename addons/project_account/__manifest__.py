{
    "name": "Project - Account",
    "category": "Accounting/Accounting",
    "summary": "project profitability items computation",
    "description": """
Allows the computation of some section for the project profitability
==================================================================================================
This module allows the computation of the 'Vendor Bills', 'Other Costs' and 'Other Revenues' section for the project profitability, in the project update view.
""",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "account",
        "project",
    ],
    "data": [
        "views/account_analytic_line_views.xml",
        "views/project_project_views.xml",
        "views/project_task_views.xml",
        "views/project_sharing_project_task_views.xml",
    ],
    "auto_install": True,
}
