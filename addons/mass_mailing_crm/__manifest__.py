# -*- coding: utf-8 -*-
{
    'name': 'Mass mailing on lead / opportunities',
    'category': 'Marketing/Email Marketing',
    'version': '1.0',
    'summary': 'Add lead / opportunities UTM info on mass mailing',
    'description': """UTM and mass mailing on lead / opportunities""",
    'depends': ['crm', 'mass_mailing'],
    'data': [
        'views/mailing_mailing_views.xml',
    ],
    'demo': [
        'demo/mailing_mailing.xml',
    ],
    'auto_install': True,
    'author': 'Odoo S.A.',
    'license': 'LGPL-3',
}
