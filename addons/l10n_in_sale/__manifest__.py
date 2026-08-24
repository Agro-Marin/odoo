# -*- coding: utf-8 -*-
{
    'name': 'Indian - Sale Report(GST)',
    'version': '1.0',
    'description': """GST Sale Report""",
    'category': 'Accounting/Localizations/Sale',
    'depends': [
        'l10n_in',
        'sale',
    ],
    'data': [
        'views/sale_order_views.xml',
    ],
    'demo': [
        'data/product_demo.xml',
    ],
    'installable': True,
    'auto_install': True,
    'author': 'Odoo S.A.',
    'license': 'LGPL-3',
}
