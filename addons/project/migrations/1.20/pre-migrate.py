MODELS = ("project.template.create.wizard",)

# object buttons, matched as the whole attribute value
ARCH_RENAMES = (
    ("create_project_from_template", "action_create_project_from_template"),
)


def _rewrite_attribute(expr, old, new):
    """SQL rewriting a whole ``name="old"`` attribute value in ``expr``.

    :param str expr: SQL expression to rewrite
    :param str old: name as it was written
    :param str new: name to write instead
    :return: SQL expression with the rename applied
    :rtype: str
    """
    return rf"""replace({expr}, 'name="{old}"', 'name="{new}"')"""


def _rewrite_xpath_predicate(expr, old, new):
    """SQL rewriting an ``@name='old'`` xpath predicate in ``expr``.

    An inheriting view targets the button by predicate rather than by
    attribute, so the two spellings are quoted differently and neither
    substitution finds the other.

    :param str expr: SQL expression to rewrite
    :param str old: name as it was written
    :param str new: name to write instead
    :return: SQL expression with the rename applied
    :rtype: str
    """
    return rf"""replace({expr}, '@name=''{old}''', '@name=''{new}''')"""


def _rename_view_buttons(cr):
    """Repoint the button and every xpath aimed at it, before the XML loads.

    This runs in ``pre-migrate`` and not beside its 1.19 counterpart because
    the stale arch breaks the load itself: importing this module's own view
    revalidates every view inheriting it, and a downstream xpath still naming
    the old button raises ``ParseError`` before ``post-migrate`` is reached.

    :param cr: database cursor
    """
    for old, new in ARCH_RENAMES:
        rewritten = _rewrite_xpath_predicate(
            _rewrite_attribute("arch_db::text", old, new), old, new
        )
        cr.execute(
            f"""
            UPDATE ir_ui_view
               SET arch_db = {rewritten}::jsonb
             WHERE (arch_db::text LIKE %s OR arch_db::text LIKE %s)
               AND model = ANY(%s)
            """,
            (f'%name="{old}"%', f"%@name='{old}'%", list(MODELS)),
        )


def migrate(cr, version):
    """Carry the ``action_`` prefix into the stored arch that names the button.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return

    _rename_view_buttons(cr)
