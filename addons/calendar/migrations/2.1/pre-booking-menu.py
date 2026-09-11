"""Retire the stock duplicate shortcut without deleting menu customizations."""

from odoo.db.schema import column_exists
from odoo.tools import SQL


def migrate(cr, version):
    if not version:
        return
    # Keep this legacy XML ID outside source-data cleanup. Existing references
    # still resolve to their original record, even when its shortcut is hidden.
    # A customized menu remains active: its children, access groups, name, action
    # or position may express an intentional navigation structure. Preserve
    # translated labels conservatively: their stock/custom origin is unknown.
    keywords_guard = (
        SQL("AND menu.web_keywords IS NULL")
        if column_exists(cr, "ir_ui_menu", "web_keywords")
        else SQL("")
    )
    cr.execute(
        SQL(
            """
        UPDATE ir_ui_menu menu SET active = false
          FROM ir_model_data legacy, ir_model_data root, ir_model_data action
         WHERE legacy.module = 'calendar'
           AND legacy.name = 'appointment_menu_calendar'
           AND legacy.model = 'ir.ui.menu'
           AND NOT legacy.noupdate
           AND menu.id = legacy.res_id
           AND root.module = 'calendar' AND root.name = 'mail_menu_calendar'
           AND action.module = 'calendar' AND action.name = 'appointment_type_action'
           AND menu.parent_id = root.res_id
           AND menu.action = 'ir.actions.act_window,' || action.res_id::text
           AND menu.name = '{"en_US": "Appointments"}'::jsonb
           AND menu.sequence = 10
           AND coalesce(menu.web_icon, '') = ''
           %s
           AND NOT EXISTS (
               SELECT 1 FROM ir_attachment icon
                WHERE icon.res_model = 'ir.ui.menu' AND icon.res_id = menu.id
                  AND icon.res_field = 'web_icon_data'
           )
           AND NOT EXISTS (SELECT 1 FROM ir_ui_menu child WHERE child.parent_id = menu.id)
           AND NOT EXISTS (SELECT 1 FROM ir_ui_menu_group_rel menu_group WHERE menu_group.menu_id = menu.id)
    """,
            keywords_guard,
        )
    )
    cr.execute("""
        UPDATE ir_model_data SET noupdate = true
         WHERE module = 'calendar' AND name = 'appointment_menu_calendar'
           AND model = 'ir.ui.menu'
    """)
