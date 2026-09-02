{
    "name": "Recruitment - Skills Management",
    "version": "1.0",
    "category": "Human Resources/Recruitment",
    "sequence": 270,
    "summary": "Manage skills of your employees",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "hr_skills",
        "hr_recruitment",
    ],
    "data": [
        "security/hr_recruitment_skills_security.xml",
        "views/hr_applicant_views.xml",
        "views/hr_applicant_skill_views.xml",
        "views/hr_job_views.xml",
        "security/ir.model.access.csv",
    ],
    "demo": [
        "data/hr_recruitment_skills_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "hr_recruitment_skills/static/src/**/*",
        ],
    },
    "installable": True,
    "auto_install": True,
}
