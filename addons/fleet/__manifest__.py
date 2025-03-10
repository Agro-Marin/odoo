# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name' : 'Fleet',
    'version' : '0.1',
    'sequence': 185,
    'category': 'Human Resources/Fleet',
    'website' : 'https://www.odoo.com/app/fleet',
    'summary' : 'Manage your fleet and track car costs',
    'description' : '''
        Vehicle, leasing, insurances, cost
        ==================================
        With this module, Odoo helps you managing all your vehicles, the
        contracts associated to those vehicle as well as services, costs
        and many other features necessary to the management of your fleet
        of vehicle(s)

        Main Features
        -------------
        * Add vehicles to your fleet
        * Manage contracts for vehicles
        * Reminder when a contract reach its expiration date
        * Add services, odometer values for all vehicles
        * Show all costs associated to a vehicle or to a type of service
        * Analysis graph for costs
    ''',
    'depends': [
        'hr',
        'product',
    ],
    'data': [
        'security/fleet_security.xml',
        'security/ir.model.access.csv',
        'data/fleet_vehicle_model_brand_data.xml',
        'data/mail_message_subtype_data.xml',
        'data/mail_activity_plan_template_data.xml',
        'data/ir_actions_server_data.xml',
        'data/product_category_data.xml',
        'data/product_product_data.xml',
        'views/res_config_settings_views.xml',
        'views/ir_attachment_views.xml',
        'views/res_users_views.xml',
        'views/fleet_vehicle_model_brand_views.xml',
        'views/fleet_vehicle_model_category_views.xml',
        'views/fleet_vehicle_model_views.xml',
        'views/fleet_vehicle_log_views.xml',
        'views/fleet_vehicle_tag_views.xml',
        'views/fleet_vehicle_views.xml',
        'views/hr_employee_views.xml',
        'views/product_template_views.xml',
        'views/fleet_menuitem.xml',
        'wizard/fleet_vehicle_send_mail_views.xml',
        'wizard/hr_departure_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'fleet/static/src/**/*',
        ],
    },
    'demo': ['data/fleet_demo.xml'],
    'license': 'LGPL-3',
    'application': True,
    'installable': True,
}
