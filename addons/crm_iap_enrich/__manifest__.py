{
    "name": "Lead Enrichment",
    "version": "1.1",
    "category": "Sales/CRM",
    "summary": "Enrich Leads/Opportunities using email address domain",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "iap_crm",
        "iap_mail",
    ],
    "data": [
        "data/ir_cron.xml",
        "data/ir_action.xml",
        "data/mail_templates.xml",
        "views/crm_lead_views.xml",
        "views/res_config_settings_view.xml",
    ],
    "auto_install": True,
    "post_init_hook": "_synchronize_cron",
}
