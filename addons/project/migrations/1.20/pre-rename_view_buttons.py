MODELS = ("project.template.create.wizard",)

ARCH_RENAMES = (
    ("create_project_from_template", "action_create_project_from_template"),
)


def _rewrite_attribute(expr, old, new):
    return rf"""replace({expr}, 'name="{old}"', 'name="{new}"')"""


def _rewrite_xpath_predicate(expr, old, new):
    return rf"""replace({expr}, '@name=''{old}''', '@name=''{new}''')"""


def _rename_view_buttons(cr):
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
    if not version:
        return

    _rename_view_buttons(cr)
