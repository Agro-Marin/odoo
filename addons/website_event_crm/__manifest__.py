{
    "name": "Website Events CRM",
    "version": "1.0",
    "category": "Website/Website",
    "description": "Allow per-order lead creation mode",
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/app/events",
    "license": "LGPL-3",
    "depends": [
        "event_crm",
        "website_event",
    ],
    "data": [
        "views/event_lead_rule_views.xml",
    ],
    "demo": [
        "data/event_crm_demo.xml",
    ],
    "installable": True,
    "auto_install": True,
}
