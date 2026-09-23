{
    "name": "HR - Livechat",
    "version": "1.0",
    "category": "Human Resources",
    "description": """
Bridge between HR and Livechat.""",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "hr",
        "im_livechat",
    ],
    "data": [
        "views/discuss_channel_views.xml",
        "views/im_livechat_channel_member_history_views.xml",
        "views/im_livechat_report_channel_views.xml",
    ],
    "assets": {
        "im_livechat.embed_assets_unit_tests_setup": [
            (
                "remove",
                "hr/static/src/**/*",
            ),
            "hr/static/src/core/common/**/*",
        ],
    },
    "auto_install": True,
}
