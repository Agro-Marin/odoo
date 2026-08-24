# -*- coding: utf-8 -*-
{
    'name': "Spreadsheet dashboard for live chat",
    'version': '1.0',
    'category': 'Productivity/Dashboard',
    'summary': 'Spreadsheet',
    'description': 'Spreadsheet',
    'depends': ['spreadsheet_dashboard', 'im_livechat'],
    'data': [
        "data/livechat_ongoing_sessions_actions.xml",
        "data/dashboards.xml",
    ],
    'installable': True,
    'auto_install': ['im_livechat'],
    'author': 'Odoo S.A.',
    'license': 'LGPL-3',
}
