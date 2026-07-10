"""Deduplicate ``ir.default`` rows before the new per-scope UNIQUE index.

A concurrent ``ir.default.set()`` race can leave several rows for one
``(field_id, user_id, company_id, condition)`` scope; read paths use the lowest
id, so the rest are dead weight the UNIQUE index would reject. Delete them
(keeping the lowest id, matching read order) so ``ir_default_unique_scope`` can
be built. Runs as a ``pre`` migration. Idempotent.
"""


def migrate(cr, version):
    cr.execute(
        """
        DELETE FROM ir_default a
              USING ir_default b
              WHERE a.field_id = b.field_id
                AND a.id > b.id
                AND COALESCE(a.user_id, 0) = COALESCE(b.user_id, 0)
                AND COALESCE(a.company_id, 0) = COALESCE(b.company_id, 0)
                AND COALESCE(a.condition, '') = COALESCE(b.condition, '')
        """
    )
