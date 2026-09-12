{
    "name": "Approvals",
    "version": "19.0.1.0.0",
    "category": "Human Resources/Approvals",
    "sequence": 190,
    "summary": "Raise, review and configure approval requests from one application",
    "description": """
Approvals
=========

The application over the approval engine: the Approvals menu, the generic
request categories people raise by hand (Business Trip, Borrow Items,
Procurement, ...) and their demo.

``approval`` is infrastructure. ``hr``, ``website_slides``, ``web_studio`` and
every module adopting ``mixin.approval`` depend on it, so an application tile
and eight request categories in the engine appeared on every database that
installed any of them. The engine keeps the models, security, decision ledger
and the forms an approver decides from; this module is what a company installs
when it wants approvals as a product.
""",
    "author": "AgroMarin",
    "license": "LGPL-3",
    "depends": [
        "approval",
    ],
    "data": [
        "data/approval_category_data.xml",
        "views/approvals_menuitem_views.xml",
    ],
    "demo": [
        "demo/00_approval_users_demo.xml",
        "demo/01_approval_groups_demo.xml",
        "demo/approval_demo.xml",
    ],
    "assets": {
        "web.assets_tests": [
            "approval_app/static/tests/tours/**/*",
        ],
    },
    "application": True,
    "pre_init_hook": "_pre_init_refuse_to_reset_the_engine_shell",
}
