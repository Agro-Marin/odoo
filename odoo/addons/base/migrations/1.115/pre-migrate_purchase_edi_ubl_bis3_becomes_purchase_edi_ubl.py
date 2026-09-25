from odoo.tools.module_data import rename_module


def migrate(cr, version):
    if not version:
        return
    rename_module(cr, "purchase_edi_ubl_bis3", "purchase_edi_ubl")
