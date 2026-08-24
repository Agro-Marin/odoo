{
    'name': 'Partners Geolocation',
    'version': '2.1',
    'category': 'Sales/Sales',
    'description': """
Partners Geolocation
========================
    """,
    'depends': ['web'],
    'data': [
        'security/ir.model.access.csv',
        'views/geo_provider_view.xml',
        'views/res_partner_views.xml',
        'views/res_config_settings_views.xml',
        'data/data.xml',
    ],
    'installable': True,
    'author': 'Odoo S.A.',
    'license': 'LGPL-3',
}
