MODELS = ("project.project", "project.phase", "project.workflow.step", "project.task")

CODE_RENAMES = (
    ("_cron_refresh_metrics", "_cron_reset_metrics"),
    ("action_refresh_metrics", "action_reset_metrics"),
    ("_refresh_metrics", "_reset_metrics"),
    ("unlink_wizard", "action_open_delete_wizard"),
    ("check_features_enabled", "get_features_enabled"),
    ("toggle_is_reached", "update_is_reached"),
    ("step_find", "get_step_id"),
    ("arrange_tag_list_by_id", "sort_tags_by_ids"),
)

CALL_RENAMES = (("project_update_all_action", "action_view_project_updates"),)

ARCH_RENAMES = (
    ("project_update_all_action", "action_view_project_updates"),
    ("unlink_wizard", "action_open_delete_wizard"),
)


def _rewrite_word(expr, old, new):
    return rf"regexp_replace({expr}, '\y{old}\y', '{new}', 'g')"


def _rewrite_call(expr, old, new):
    return rf"regexp_replace({expr}, '\y{old}\s*\(', '{new}(', 'g')"


def _rewrite_attribute(expr, old, new):
    return rf"""replace({expr}, 'name="{old}"', 'name="{new}"')"""


def _rename_server_action_code(cr):
    for old, new in CODE_RENAMES:
        cr.execute(
            f"""
            UPDATE ir_act_server
               SET code = {_rewrite_word("code", old, new)}
             WHERE code ~ '\\y{old}\\y'
            """
        )
    for old, new in CALL_RENAMES:
        cr.execute(
            f"""
            UPDATE ir_act_server
               SET code = {_rewrite_call("code", old, new)}
             WHERE code ~ '\\y{old}\\s*\\('
            """
        )


def _rename_view_buttons(cr):
    for old, new in ARCH_RENAMES:
        cr.execute(
            f"""
            UPDATE ir_ui_view
               SET arch_db = {_rewrite_attribute("arch_db::text", old, new)}::jsonb
             WHERE arch_db::text LIKE %s
               AND model = ANY(%s)
            """,
            (f'%name="{old}"%', list(MODELS)),
        )


def migrate(cr, version):
    if not version:
        return

    _rename_server_action_code(cr)
    _rename_view_buttons(cr)
