{
    "name": "Module Install Request Approvals",
    "version": "19.0.1.0.0",
    "category": "Hidden",
    "summary": "An activation request is decided through the approval engine",
    "description": """
Module Install Request Approvals
================================

Where the approval engine is installed, a user asking the administrators to
activate a module raises an approval request instead of sending each of them
an e-mail: who asked, who decided and what they said are recorded, and the
administrator installs from the approved request.

A bridge rather than a dependency of ``base_install_request`` on purpose. That
module is auto-installed on every database; a dependency there is a dependency
of every database, and a database that never had ``approval`` skips the module
on its next start rather than upgrading into it.
""",
    "author": "AgroMarin",
    "license": "LGPL-3",
    "depends": [
        "approval",
        "base_install_request",
    ],
    "data": [
        "data/approval_category_data.xml",
        "views/base_module_install_request_views.xml",
    ],
    "auto_install": True,
    "post_init_hook": "_forbid_self_approval",
}
