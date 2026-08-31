INDIVIDUAL_SKILL_FIELDS = ("valid_from", "valid_to", "skill_level_id", "skill_type_id")


def _individual_skill_tables(cr):
    cr.execute(
        """
        SELECT m.model, count(DISTINCT f.name) AS matched
          FROM ir_model m
          JOIN ir_model_fields f ON f.model_id = m.id
         WHERE f.name = ANY(%s)
      GROUP BY m.model
        HAVING count(DISTINCT f.name) = %s
        """,
        (list(INDIVIDUAL_SKILL_FIELDS), len(INDIVIDUAL_SKILL_FIELDS)),
    )
    candidates = [model.replace(".", "_") for model, _ in cr.fetchall()]
    if not candidates:
        return []
    cr.execute(
        """
        SELECT table_name
          FROM information_schema.columns
         WHERE table_name = ANY(%s)
           AND column_name = 'valid_from'
        """,
        (candidates,),
    )
    return [table for (table,) in cr.fetchall()]


def migrate(cr, version):
    if not version:
        return
    for table in _individual_skill_tables(cr):
        cr.execute(
            f"""
            UPDATE {table}
               SET valid_from = COALESCE(create_date::date, CURRENT_DATE)
             WHERE valid_from IS NULL
            """
        )
