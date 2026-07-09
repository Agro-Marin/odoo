"""Deduplicate ``ir.default`` rows before the new per-scope UNIQUE index.

A concurrent ``ir.default.set()`` race (two transactions both missing on
``_get_default_record`` and both creating) leaves several rows for one
``(field_id, user_id, company_id, condition)`` scope.  Every read path picks the
lowest id, so the extra rows are dead weight the UNIQUE index would now reject at
creation time.  Delete them here (keeping the lowest id, matching read order) so
the index can be built.  Runs as a ``pre`` migration, before base reloads its
schema and adds ``ir_default_unique_scope``.  Idempotent.
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
