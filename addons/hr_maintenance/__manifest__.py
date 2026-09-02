{
    "name": "Maintenance - HR",
    "version": "1.0",
    "category": "Human Resources",
    "sequence": 125,
    "summary": "Equipment, Assets, Internal Hardware, Allocation Tracking",
    "description": """
Bridge between HR and Maintenance.""",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "hr",
        "maintenance",
    ],
    "data": [
        "security/equipment.xml",
        "views/maintenance_views.xml",
        "views/hr_views.xml",
        "wizard/hr_departure_wizard_views.xml",
    ],
    "installable": True,
    "auto_install": True,
}
