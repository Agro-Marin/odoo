from odoo.tools.module_data import adopt_xmlids

RECORDS = tuple(
    f"field_{model}__{field}"
    for model in ("product_template", "product_product")
    for field in ("taxes_id", "supplier_taxes_id", "tax_string")
)

RELATIONS = ("product_taxes_rel", "product_supplier_taxes_rel")


def migrate(cr, version):
    if not version:
        return
    # before account loads: an xml id left under account would be orphaned when
    # account stops declaring the field, and _process_end would drop its column
    adopt_xmlids(cr, "account", "tax", RECORDS)
    cr.execute(
        """
        UPDATE ir_model_relation rel
           SET module = tax.id
          FROM ir_module_module tax, ir_module_module account
         WHERE tax.name = 'tax' AND account.name = 'account'
           AND rel.module = account.id AND rel.name = ANY(%s)
        """,
        [list(RELATIONS)],
    )
