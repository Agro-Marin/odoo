# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Accounting/Fleet bridge',
    'category': 'Accounting/Accounting',
    'summary': 'Manage accounting with fleets',
    'version': '1.0',
    'depends': ['fleet', 'account'],
    'data': [
        'views/account_move_views.xml',
        'views/fleet_vehicle_views.xml',
        'views/fleet_vehicle_log_views.xml'
    ],
    'installable': True,
    'auto_install': True,
    'license': 'LGPL-3',
}
