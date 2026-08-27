{
    "name": "Attachments List and Document Indexation",
    "version": "2.1",
    "category": "Hidden/Tools",
    "description": """
Attachments list and document indexation
========================================
* Show attachment on the top of the forms
* Document Indexation: odt, pdf, xlsx, docx

The `pdfminer.six` Python library has to be installed in order to index PDF files
""",
    "depends": ["web"],
    "external_dependencies": {
        "python": ["defusedxml", "openpyxl", "pdfminer"],
        "apt": {
            "defusedxml": "python3-defusedxml",
            "openpyxl": "python3-openpyxl",
            "pdfminer": "python3-pdfminer",
        },
    },
    "installable": True,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
}
