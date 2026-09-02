# -*- coding: utf-8 -*-
{
    "name": "Accounting/Fleet bridge",
    "version": "1.0",
    "category": "Accounting/Accounting",
    "summary": "Manage accounting with fleets",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "fleet",
        "account",
    ],
    "data": [
        "data/fleet_service_type_data.xml",
        "views/account_move_views.xml",
        "views/fleet_vehicle_views.xml",
        "views/fleet_vehicle_log_services_views.xml",
    ],
    "installable": True,
    "auto_install": True,
}
