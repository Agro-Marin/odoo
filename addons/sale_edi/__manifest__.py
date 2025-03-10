{
    "name": "Import sale orders from attachment",
    "description": """
It provides tools to import and process sales orders from attachments
(e.g., PDFs, binary files, or other EDI formats). The module is designed
to help businesses avoid duplicate orders and streamline the order
creation process by extracting data from uploaded files.
    """,
    "category": "Sale",
    "version": "1.0",
    "depends": ["sale"],
    "data": [
        "views/sale_order_views.xml",
    ],
}
