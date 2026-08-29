{
    "name": "Data Recycle",
    "version": "1.4",
    "category": "Productivity/Data Cleaning",
    "summary": "Find old records and archive/delete them",
    "description": """Find old records and archive/delete them""",
    "depends": ["mail"],
    "data": [
        "data/ir_cron_data.xml",
        "views/data_recycle_model_views.xml",
        "views/data_recycle_record_views.xml",
        "views/data_cleaning_menu.xml",
        "views/data_recycle_templates.xml",
        "security/ir.model.access.csv",
        "security/ir_rule.xml",
    ],
    "installable": True,
    "application": True,
    "assets": {
        "web.assets_backend": [
            "data_recycle/static/src/cog_menu/*.js",
            "data_recycle/static/src/cog_menu/*.xml",
            "data_recycle/static/src/views/*.js",
            "data_recycle/static/src/views/*.xml",
        ],
        "web.assets_tests": [
            "data_recycle/static/tests/tours/*.js",
        ],
    },
    "author": "Odoo S.A.",
    "license": "LGPL-3",
}
