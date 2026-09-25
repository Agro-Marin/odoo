{
    "name": "Stock Transport - Delivery",
    "version": "1.0",
    "category": "Supply Chain/Inventory",
    "summary": "How each carrier dispatches: own fleet, salesperson, third party or pickup",
    "description": """
Each carrier says how its goods leave. Own fleet and salesperson deliveries travel
in a trip that has departed; a third-party carrier needs its tracking reference
instead; a customer pickup needs neither.
""",
    "author": "AgroMarin",
    "website": "https://www.agromarin.mx",
    "license": "LGPL-3",
    "depends": [
        "stock_fleet",
        "stock_delivery",
    ],
    "data": [
        "views/delivery_carrier_views.xml",
    ],
    "auto_install": True,
}
