{
    "name": "Web Routing",
    "category": "Hidden",
    "sequence": 9100,
    "summary": "Web Routing",
    "description": """
Proposes advanced routing options not available in web or base to keep
base modules simple.
""",
    "author": "Odoo S.A.",
    "license": "LGPL-3",
    "depends": [
        "web",
    ],
    "data": [
        "views/http_routing_template.xml",
        "views/res_lang_views.xml",
    ],
    "post_init_hook": "_post_init_hook",
}
