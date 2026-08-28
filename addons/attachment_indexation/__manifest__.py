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
    # openpyxl and pdfminer.six are NOT declared: both are guarded in
    # models/ir_attachment.py -- `try/except ImportError` and `find_spec` -- so
    # the module starts and indexes everything else without them. Declaring one
    # would refuse the install instead of degrading. defusedxml is imported at
    # module level and has no guard, so it is the one that belongs here.
    "external_dependencies": {
        "python": ["defusedxml"],
        "apt": {"defusedxml": "python3-defusedxml"},
    },
    "installable": True,
    "author": "Odoo S.A.",
    "license": "LGPL-3",
}
