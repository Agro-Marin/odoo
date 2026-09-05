import logging

_logger = logging.getLogger(__name__)


def _columns_pointing_at_levels(cr):
    cr.execute(
        """
        SELECT m.model, f.name
          FROM ir_model_fields f
          JOIN ir_model m ON m.id = f.model_id
         WHERE f.relation = 'hr.skill.level'
           AND f.ttype = 'many2one'
           AND f.store
        """
    )
    candidates = {(model.replace(".", "_"), column) for model, column in cr.fetchall()}
    if not candidates:
        return []
    cr.execute(
        """
        SELECT table_name, column_name
          FROM information_schema.columns
         WHERE table_name = ANY(%s)
        """,
        ([table for table, _column in candidates],),
    )
    return [pair for pair in cr.fetchall() if pair in candidates]


def migrate(cr, version):
    """skill_type_id becomes required. A level without a type can never be
    picked -- every picker reads skill_type_id.skill_level_ids -- so the
    unreferenced ones are deleted; a referenced one is kept and reported, and
    the NOT NULL constraint is then refused by the ORM with a warning."""
    if not version:
        return
    cr.execute("SELECT id FROM hr_skill_level WHERE skill_type_id IS NULL")
    orphans = {row[0] for row in cr.fetchall()}
    if not orphans:
        return
    referenced = set()
    for table, column in _columns_pointing_at_levels(cr):
        cr.execute(
            f"SELECT DISTINCT {column} FROM {table} WHERE {column} = ANY(%s)",
            (list(orphans),),
        )
        referenced.update(row[0] for row in cr.fetchall())
    to_delete = list(orphans - referenced)
    if to_delete:
        cr.execute("DELETE FROM hr_skill_level WHERE id = ANY(%s)", (to_delete,))
    if referenced:
        _logger.warning(
            "hr.skill.level rows %s have no skill type but are referenced; "
            "give each a type by hand",
            sorted(referenced),
        )
