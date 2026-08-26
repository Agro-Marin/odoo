from odoo.addons.document_extract.tools import FieldSpec, extend_schema

extend_schema(
    "invoice",
    fields={
        "purchase_order": FieldSpec(
            "str",
            help="Purchase order reference the bill answers, as printed on it",
        ),
    },
)
