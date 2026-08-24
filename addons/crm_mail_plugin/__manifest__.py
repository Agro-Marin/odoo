# -*- coding: utf-8 -*-
{
    'name': 'CRM Mail Plugin',
    'version': '1.0',
    'category': 'Sales/CRM',
    'sequence': 5,
    'summary': 'Turn emails received in your mailbox into leads and log their content as internal notes.',
    'description': "Turn emails received in your mailbox into leads and log their content as internal notes.",
    'website': 'https://www.odoo.com/app/crm',
    'depends': [
        'crm',
        'mail_plugin',
    ],
    'data': [
        'views/crm_mail_plugin_lead.xml',
        'views/crm_lead_views.xml'
    ],
    'installable': True,
    'auto_install': True,
    'author': 'Odoo S.A.',
    'license': 'LGPL-3',
}
