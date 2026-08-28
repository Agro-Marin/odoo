r"""Pre-migration: ``documents.document`` favorites move onto ``mixin.user.favorite``.

``favorited_ids`` is now ``favorite_user_ids`` and ``is_favorited`` is now
``is_user_favorite`` -- the canonical spellings, replacing the second of the five
this tree used for one concept.

**No table moves.** ``favorited_ids`` was already declared without a
``relation=``, so the ORM had derived ``documents_document_res_users_rel`` for it,
which is exactly the name the mixin derives for the adopter. Verified against a
real install: the table and both column names come out identical.

``is_favorited`` is ``store=False``, so no column of its own moves either. What
moves is every stored artifact naming either field -- and a domain naming a field
the registry no longer has raises when the domain is READ, not when the module is
upgraded, so an unrewritten filter fails later and elsewhere. Module-owned view
arch is reloaded from XML by the upgrade itself; these statements exist for the
artifacts users made.

Every statement is idempotent: the guard stops matching once a row is rewritten.
"""

MODEL = "documents.document"
RENAMES = (("favorited_ids", "favorite_user_ids"), ("is_favorited", "is_user_favorite"))


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


def migrate(cr, version):
    """Repoint stored domains from the old field names to the new ones.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return

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
