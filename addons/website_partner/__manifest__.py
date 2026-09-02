{
    "name": "Website Partner",
    "version": "0.1",
    "category": "Website/Website",
    "summary": "Partner module for website",
    "description": """
This is a base module. It holds website-related stuff for Contact model (res.partner).
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "website",
    ],
    "data": [
        "views/res_partner_views.xml",
        "views/website_partner_templates.xml",
        "data/website_partner_data.xml",
    ],
    "demo": [
        "data/website_partner_demo.xml",
    ],
    "installable": True,
}
