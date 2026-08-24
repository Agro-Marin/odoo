# -*- coding: utf-8 -*-
{
    'name': 'DIN 5008 - Stock',
    'category': 'Accounting/Localizations',
    'depends': [
        'l10n_din5008',
        'stock',
    ],
    'data': [
        'report/din5008_stock_templates.xml',
        'report/din5008_stock_picking_layout.xml',
    ],
    'auto_install': True,
    'author': 'Odoo S.A.',
    'license': 'LGPL-3',
}
