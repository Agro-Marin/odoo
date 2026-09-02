{
    "name": "Password Policy support for Signup",
    "category": "Hidden/Tools",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "auth_password_policy",
        "auth_signup",
    ],
    "data": [
        "views/signup_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "auth_password_policy_signup/static/src/public/**/*",
            "auth_password_policy/static/src/password_meter.js",
            "auth_password_policy/static/src/password_policy.js",
        ],
    },
    "auto_install": True,
}
