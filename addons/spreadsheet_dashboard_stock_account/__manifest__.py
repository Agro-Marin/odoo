{
    'name': "Spreadsheet dashboard for stock",
    'category': 'Productivity/Dashboard',
    'summary': 'Spreadsheet',
    'description': 'Spreadsheet',
    'depends': ['spreadsheet_dashboard', 'stock_account'],
    'data': [
        "data/dashboards.xml",
    ],
    'installable': True,
    'auto_install': ['stock_account'],
    'author': 'Odoo S.A.',
    'license': 'LGPL-3',
}
