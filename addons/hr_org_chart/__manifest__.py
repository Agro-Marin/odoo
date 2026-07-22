# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'HR Org Chart',
    'category': 'Human Resources',
    'version': '1.0',
    'description':
        """
Org Chart Widget for HR
=======================

This module extend the employee form with a organizational chart.
(N+1, N+2, direct subordinates)
        """,
    'depends': ['hr', 'web_hierarchy'],
    'auto_install': ['hr'],
    'data': [
        'views/hr_department_views.xml',
        'views/hr_employee_public_views.xml',
        'views/hr_views.xml',
    ],
    'assets': {
        'web._assets_primary_variables': [
            'hr_org_chart/static/src/scss/variables.scss',
        ],
        'web.assets_backend': [
            'hr_org_chart/static/src/fields/*',
            # Hierarchy view (registry entry "hr_employee_hierarchy" and
            # its renderer/card components). Prior to commit fdad91a872c
            # these lived in ``web.assets_backend_lazy``; the ESM migration
            # dropped the lazy bundle but forgot to merge the files into
            # ``web.assets_backend``, leaving the views unregistered and
            # every navigation to the Employees hierarchy view crashing
            # with KeyNotFoundError.
            'hr_org_chart/static/src/views/**/*',
        ],
        'web.assets_tests': [
            'hr_org_chart/static/tests/tours/*.js',
        ],
        'web.assets_unit_tests': [
            'hr_org_chart/static/tests/**/*',
        ],
    },
    'author': 'Odoo S.A.',
    'license': 'LGPL-3',
}
