from odoo.tools.module_data import rename_module

RENAMES = (
    ("pos_account_tax_python", "pos_tax_python"),
    ("account_tax_python", "tax_python"),
    ("account_tax", "tax"),
)


def migrate(cr, version):
    if not version:
        return
    for old, new in RENAMES:
        rename_module(cr, old, new)
