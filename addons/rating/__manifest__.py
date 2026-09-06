{
    "name": "Customer Rating",
    "version": "1.1",
    "category": "Productivity",
    "description": """
This module allows a customer to give rating.
""",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "mail",
    ],
    "data": [
        "views/rating_rating_views.xml",
        "views/rating_templates.xml",
        "views/mail_message_views.xml",
        "security/ir.model.access.csv",
    ],
    "assets": {
        "web.assets_backend": [
            "rating/static/src/core/common/**/*",
            "rating/static/src/core/web/**/*",
            "rating/static/src/scss/rating_rating_views.scss",
        ],
        "web.assets_frontend": [
            "rating/static/src/scss/rating_templates.scss",
        ],
        "web.assets_unit_tests": [
            "rating/static/tests/**/*",
        ],
        "mail.assets_public": [
            "rating/static/src/core/common/**/*",
        ],
        # The helpers bundle, not `portal.assets_chatter` above it: a chatter
        # is assembled from the helpers, and some clients assemble their own
        # instead of pulling the whole frontend bundle in. `assets_chatter`
        # includes the helpers, so it keeps getting these files.
        "portal.assets_chatter_helpers": [
            "rating/static/src/core/common/**/*",
        ],
    },
    "installable": True,
}
