r"""Pre-migration: ``mailing.mailing`` favorites take the canonical spellings.

``favorite`` is now ``is_favorite`` (§2.3: booleans carry an ``is_`` prefix) and
``favorite_date`` is now ``date_favorite`` (§2.3: dates carry a ``date_``
prefix). The model also gains ``mixin.user.favorite`` alongside, so a mailing can
be a favorite of the database *and* of a particular user; nothing about the
existing flag moves, which is the whole point of the split.

**Both renamed fields are stored**, so unlike the other favorite migrations these
are real column renames. The schema pass would otherwise add two empty columns
beside the populated ones and every existing favorite mailing would read as not
favorited.

``date_favorite`` is computed with ``store=True``, so a lost column would be
silently repopulated from ``is_favorite`` -- with today's date on every row,
which reads as correct and is not. That is why it is renamed rather than left to
recompute.

Every statement is idempotent: the guard stops matching once a row is rewritten,
and a column rename is skipped when the old column is already gone.
"""

MODEL = "mailing.mailing"
TABLE = "mailing_mailing"
COLUMNS = (("favorite", "is_favorite"), ("favorite_date", "date_favorite"))
RENAMES = COLUMNS


def _rewrite(expr):
    """SQL rewriting every renamed token whole-word in ``expr``.

    :param str expr: SQL expression (column or cast) to rewrite
    :return: SQL expression with the renames applied
    :rtype: str
    """
    for old, new in RENAMES:
        expr = rf"regexp_replace({expr}, '\y{old}\y', '{new}', 'g')"
    return expr


def _matches(expr):
    """SQL guard true when ``expr`` still names one of the old fields.

    :param str expr: SQL expression (column or cast) to test
    :return: SQL boolean expression
    :rtype: str
    """
    return " OR ".join(rf"{expr} ~ '\y{old}\y'" for old, _new in RENAMES)


def _rename_columns(cr):
    """Carry the two stored favorite columns onto their new names.

    :param cr: database cursor
    """
    for old_column, new_column in COLUMNS:
        cr.execute(
            """
            SELECT 1 FROM information_schema.columns
             WHERE table_name = %s AND column_name = %s
            """,
            (TABLE, old_column),
        )
        if not cr.fetchone():
            continue
        cr.execute(
            f'ALTER TABLE "{TABLE}" RENAME COLUMN "{old_column}" TO "{new_column}"'
        )


def migrate(cr, version):
    """Rename the stored columns and repoint stored domains at the new names.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return

    _rename_columns(cr)

    cr.execute(
        f"""
        UPDATE ir_ui_view
           SET arch_db = {_rewrite("arch_db::text")}::jsonb
         WHERE ({_matches("arch_db::text")})
           AND model = %s
        """,
        (MODEL,),
    )
    cr.execute(
        f"""
        UPDATE ir_filters
           SET domain = {_rewrite("domain")},
               context = {_rewrite("context")},
               sort = {_rewrite("sort")}
         WHERE ({_matches("domain")}
                OR {_matches("context")}
                OR {_matches("sort")})
           AND model_id = %s
        """,
        (MODEL,),
    )
    cr.execute(
        f"""
        UPDATE ir_act_window
           SET domain = {_rewrite("domain")},
               context = {_rewrite("context")}
         WHERE ({_matches("domain")} OR {_matches("context")})
           AND res_model = %s
        """,
        (MODEL,),
    )
