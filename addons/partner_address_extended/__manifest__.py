{
    'name': 'Extended Addresses',
    'summary': 'Add extra fields on addresses',
    'sequence': 19,
    'version': '1.2',
    'category': 'Sales/Sales',
    'description': """
Extended Addresses Management
=============================

This module provides the ability to choose a city from a list (in specific countries).

It is primarily used for EDIs that might need a special city code.
        """,
    'data': [
        'security/ir.model.access.csv',
        'views/partner_address_extended.xml',
        'views/res_city_view.xml',
        'views/res_country_view.xml',
    ],
    'depends': ['partner'],
    'author': 'Odoo S.A.',
    'license': 'LGPL-3',
}
