# -*- coding: utf-8 -*-
{
    "name": "POS Self Order Sale",
    "category": "Sales/Point Of Sale",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "pos_sale",
        "pos_self_order",
    ],
    "data": [
        "views/res_config_settings_views.xml",
        "data/kiosk_sale_team.xml",
    ],
    "auto_install": True,
}
