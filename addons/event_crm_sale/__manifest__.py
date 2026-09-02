{
    "name": "Event CRM Sale",
    "version": "1.0",
    "category": "Marketing/Events",
    "description": "Add information of sale order linked to the registration for the creation of the lead.",
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/app/events",
    "license": "LGPL-3",
    "depends": [
        "event_crm",
        "event_sale",
    ],
    "data": [
        "views/event_lead_rule_views.xml",
    ],
    "installable": True,
    "auto_install": True,
}
