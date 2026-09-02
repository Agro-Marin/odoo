# -*- coding: utf-8 -*-
{
    "name": "Mass mailing on sale orders",
    "version": "1.0",
    "category": "Marketing/Email Marketing",
    "summary": "Add sale order UTM info on mass mailing",
    "description": "UTM and mass mailing on sale orders",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "sale",
        "mass_mailing",
    ],
    "data": [
        "views/mailing_mailing_views.xml",
    ],
    "demo": [
        "demo/mailing_mailing.xml",
    ],
    "auto_install": True,
}
