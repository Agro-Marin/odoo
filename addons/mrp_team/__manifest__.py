{
    "name": "Manufacturing Teams",
    "version": "1.1",
    "category": "Supply Chain/Manufacturing",
    "summary": "Production runs in teams: manufacturing orders belong to the team of their operation type",
    "author": "AgroMarin",
    "license": "LGPL-3",
    "depends": [
        "mrp",
        "stock_team",
    ],
    "data": [
        "security/mrp_team_security.xml",
        "security/ir.access.csv",
        "security/ir_access.xml",
        "views/team_team_views.xml",
        "views/mrp_production_views.xml",
        "views/mrp_team_menus.xml",
    ],
    "auto_install": True,
}
