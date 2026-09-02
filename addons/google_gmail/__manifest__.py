{
    "name": "Google Gmail",
    "version": "19.0.2.0.0",
    "category": "Hidden",
    "description": "Gmail support for incoming / outgoing mail servers",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "mail_oauth2",
        "mail",
    ],
    "data": [
        "views/fetchmail_server_views.xml",
        "views/ir_mail_server_views.xml",
        "views/res_config_settings_views.xml",
        "views/templates.xml",
    ],
    "auto_install": True,
}
