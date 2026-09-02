{
    "name": "Project Mail Plugin",
    "version": "1.0",
    "category": "Services/Project",
    "sequence": 5,
    "summary": "Integrate your inbox with projects",
    "description": "Turn emails received in your mailbox into tasks and log their content as internal notes.",
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/app/project",
    "license": "LGPL-3",
    "depends": [
        "project",
        "mail_plugin",
    ],
    "data": [
        "views/project_task_views.xml",
    ],
    "installable": True,
    "auto_install": True,
}
