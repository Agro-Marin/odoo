{
    "name": "Geocoding",
    "version": "3.0",
    "category": "Technical",
    "description": """
Geocoding
=========
Convert addresses into GPS coordinates, and coordinates back into place names,
through a pluggable provider.
    """,
    "depends": ["web"],
    "data": [
        "security/ir.model.access.csv",
        "views/geocoder_provider_views.xml",
        "views/res_partner_views.xml",
        "views/res_config_settings_views.xml",
        "data/data.xml",
    ],
    "installable": True,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
}
