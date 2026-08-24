{
    'name': 'Link Tracker',
    'category': 'Marketing',
    'summary': 'Shorten URLs and use them to track clicks and UTMs',
    'version': '19.0.1.2',
    'depends': ['utm', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/link_tracker_views.xml',
        'views/utm_campaign_views.xml',
    ],
    'author': 'Odoo S.A.',
    'license': 'LGPL-3',
}
