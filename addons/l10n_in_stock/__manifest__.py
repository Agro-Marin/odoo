# -*- coding: utf-8 -*-
{
    'name': 'Indian - Stock Report(GST)',
    'version': '1.0',
    'description': """GST Stock Report""",
    'category': 'Accounting/Localizations',
    'depends': [
        'l10n_in',
        'stock',
    ],
    'data': [
        'views/report_stockpicking_operations.xml',
    ],
    'demo': [
        'data/product_demo.xml',
    ],
    'installable': True,
    'auto_install': True,
    'author': 'Odoo S.A.',
    'license': 'LGPL-3',
}
