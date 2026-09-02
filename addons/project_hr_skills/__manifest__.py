{
    "name": "Project - Skills",
    "version": "1.0",
    "category": "Services/Project",
    "summary": "Project skills",
    "description": """
        Search project tasks according to the assignees' skills
    """,
    "author": "Odoo S.A.",
    "license": "OEEL-1",
    "depends": [
        "project_hr",
        "hr_skills",
    ],
    "data": [
        "views/project_task_views.xml",
    ],
    "auto_install": True,
}
