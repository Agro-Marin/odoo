{
    "name": "Events Product",
    "version": "1.0",
    "category": "Marketing/Events",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "event",
        "product",
        "account",
    ],
    "data": [
        "views/event_ticket_views.xml",
        "views/event_registration_views.xml",
        "data/event_product_data.xml",
    ],
    "demo": [
        "data/event_product_demo.xml",
        "data/event_demo.xml",
    ],
    "installable": True,
    "auto_install": True,
}
