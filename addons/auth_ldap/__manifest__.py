{
    "name": "Authentication via LDAP",
    "category": "Hidden/Tools",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "web",
    ],
    "external_dependencies": {
        "python": [
            "python-ldap",
        ],
        "apt": {
            "python-ldap": "python3-ldap",
        },
    },
    "data": [
        "views/ldap_installer_views.xml",
        "security/ir.model.access.csv",
        "views/res_config_settings_views.xml",
    ],
}
