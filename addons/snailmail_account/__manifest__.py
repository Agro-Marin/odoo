# -*- coding: utf-8 -*-
{
    "name": "Snail Mail - Account",
    "version": "0.1",
    "category": "Hidden/Tools",
    "description": """
Allows users to send invoices by post
=====================================================
        """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "account",
        "snailmail",
    ],
    "data": [
        "views/res_config_settings_views.xml",
    ],
    "auto_install": True,
}
