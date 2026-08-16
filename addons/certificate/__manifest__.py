{
    "name": "Certificate",
    "version": "19.0.1.0.0",
    "category": "Hidden/Tools",
    "summary": "Manage certificate",
    "installable": True,
    "data": [
        "security/ir.model.access.csv",
        "security/certificate_security.xml",
        "views/certificate_views.xml",
        "views/key_views.xml",
        "views/action_menus.xml",
        "views/res_config_settings_view.xml",
    ],
    "depends": ["web", "base_encryption_mixin"],
    "author": "Odoo S.A.",
    "license": "AGPL-3",
}
