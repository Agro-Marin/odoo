{
    "name": "Send SMS to Visitor",
    "version": "1.0",
    "category": "Website/Website",
    "sequence": 54,
    "summary": "Allows to send sms to website visitor",
    "description": "Allows to send sms to website visitor if the visitor is linked to a partner.",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "website",
        "sms",
    ],
    "data": [
        "views/website_visitor_views.xml",
    ],
    "installable": True,
    "auto_install": True,
}
