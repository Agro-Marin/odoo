{
    "name": "MRP Subcontracting Repair",
    "version": "1.0",
    "category": "Supply Chain/Repair",
    "description": """
Bridge module between MRP subcontracting and Repair
    """,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "mrp_subcontracting",
        "repair",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/mrp_subcontracting_repair_security.xml",
    ],
    "installable": True,
    "auto_install": True,
}
