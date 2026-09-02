MODELS = ("project.template.create.wizard",)

# object buttons, matched as the whole attribute value
ARCH_RENAMES = (
    ("create_project_from_template", "action_create_project_from_template"),
)


def _rewrite_attribute(expr, old, new):
    """SQL rewriting a whole ``name="old"`` attribute value in ``expr``.

    :param str expr: SQL expression holding one language's arch, unescaped
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

    :param str expr: SQL expression holding one language's arch, unescaped
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

    Rewriting goes through ``jsonb_each_text`` and not ``arch_db::text``.
    ``arch_db`` is a jsonb map of language to arch, so its text rendering
    escapes every attribute quote -- the stored bytes read
    ``name=\\"create_project_from_template\\"`` -- and a pattern spelling
    ``name="create_project_from_template"`` matches nothing while reporting
    success. Decomposing to values hands each language its arch unescaped, and
    ``jsonb_object_agg`` puts the map back with every language kept.

    :param cr: database cursor
    """
    for old, new in ARCH_RENAMES:
        rewritten = _rewrite_xpath_predicate(
            _rewrite_attribute("kv.value", old, new), old, new
        )
        cr.execute(
            f"""
            UPDATE ir_ui_view v
               SET arch_db = (
                     SELECT jsonb_object_agg(kv.key, {rewritten})
                       FROM jsonb_each_text(v.arch_db) kv
                   )
             WHERE v.model = ANY(%s)
               AND EXISTS (
                     SELECT 1 FROM jsonb_each_text(v.arch_db) kv
                      WHERE kv.value LIKE %s OR kv.value LIKE %s
                   )
            """,
            (list(MODELS), f'%name="{old}"%', f"%@name='{old}'%"),
        )


def migrate(cr, version):
    """Carry the ``action_`` prefix into the stored arch that names the button.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return

    _rename_view_buttons(cr)
