# -*- coding: utf-8 -*-
{
    'name': "Spreadsheet dashboard for expenses",
    'version': '1.0',
    'category': 'Productivity/Dashboard',
    'summary': 'Spreadsheet',
    'description': 'Spreadsheet',
    'depends': ['spreadsheet_dashboard', 'sale_expense'],
    'data': [
        "data/dashboards.xml",
    ],
    'installable': True,
    'auto_install': ['sale_expense'],
    'author': 'Odoo S.A.',
    'license': 'LGPL-3',
}
