{
    "name": "Lead Livechat Sessions",
    "version": "1.0",
    "category": "Website/Website",
    "summary": "View livechat sessions for leads",
    "description": " Adds a stat button on lead form view to access their livechat sessions.",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "website_crm",
        "website_livechat",
    ],
    "data": [
        "views/website_crm_lead_views.xml",
    ],
    "installable": True,
    "auto_install": True,
}
