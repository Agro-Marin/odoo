{
    "name": "Documents - Product",
    "version": "1.2",
    "category": "Productivity/Documents",
    "summary": "Products from Documents",
    "description": """
Adds the ability to create products from the document module and adds the
option to send products' attachments to the documents app.
""",
    "author": "Odoo S.A.",
    "website": "https://www.odoo.com/app/documents",
    "license": "LGPL-3",
    "depends": [
        "documents",
        "product",
    ],
    "data": [
        "data/documents_folder_data.xml",
        "data/documents_tag_data.xml",
        "data/res_company_data.xml",
        "views/res_config_settings_views.xml",
        "views/documents_document_views.xml",
        "views/documents_document_product_views.xml",
        "views/product_views.xml",
    ],
    "demo": [
        "demo/documents_document_demo.xml",
    ],
    "auto_install": True,
}
