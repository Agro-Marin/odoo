"""Post-migration: ``res.partner.industry_id`` became ``industry_ids``.

A contact can operate in several sectors at once -- a grower that also runs a
packing house is Agriculture and Manufacturing on the same day -- so the single
``industry_id`` many2one is now the ``industry_ids`` many2many.

``primary_industry_id`` stays a many2one because an analytical report cannot
split one sum across several sectors. ``sale.report`` selects it, and joining
the many2many there would emit an order line once per sector and double-count
revenue.

Each row carries exactly one industry after this script, so the stored compute
that the loader flushes right after this runs converges on the same value it
writes here: the first, and only, member of ``industry_ids``.
"""

from odoo.db.schema import column_exists

OLD_COLUMN = "industry_id"
REL_TABLE = "res_partner_industry_rel"


def migrate(cr, version):
    if not version:
        return
    if not column_exists(cr, "res_partner", OLD_COLUMN):
        return

    cr.execute(
        f"""
        INSERT INTO {REL_TABLE} (partner_id, industry_id)
        SELECT p.id, p.{OLD_COLUMN}
          FROM res_partner p
         WHERE p.{OLD_COLUMN} IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    cr.execute(
        f"""
        UPDATE res_partner p
           SET primary_industry_id = p.{OLD_COLUMN}
         WHERE p.{OLD_COLUMN} IS NOT NULL
           AND p.primary_industry_id IS DISTINCT FROM p.{OLD_COLUMN}
        """
    )
    cr.execute(f'ALTER TABLE res_partner DROP COLUMN "{OLD_COLUMN}"')
