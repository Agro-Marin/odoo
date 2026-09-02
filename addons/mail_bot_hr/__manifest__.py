{
    "name": "OdooBot - HR",
    "version": "1.0",
    "category": "Productivity/Discuss",
    "summary": "Bridge module between hr and mailbot.",
    "description": "This module adds the OdooBot state and notifications in the user form modified by hr.",
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/app/discuss",
    "license": "LGPL-3",
    "depends": [
        "mail_bot",
        "hr",
    ],
    "data": [
        "views/res_users_views.xml",
    ],
    "installable": True,
    "auto_install": True,
}
