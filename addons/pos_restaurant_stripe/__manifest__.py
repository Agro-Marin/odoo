# -*- coding: utf-8 -*-
{
    'name': 'POS Restaurant Stripe',
    'version': '1.0',
    'category': 'Point of Sale',
    'sequence': 6,
    'summary': 'Adds American style tipping to Stripe',
    'depends': ['pos_stripe', 'pos_restaurant', 'payment_stripe'],
    'auto_install': True,
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_restaurant_stripe/static/**/*',
        ],
    },
    'author': 'Odoo S.A.',
    'license': 'LGPL-3',
}
