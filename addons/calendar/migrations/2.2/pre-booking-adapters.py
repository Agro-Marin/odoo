"""Activate extracted presentation code for migrated Appointment installations.

Auto-install is triggered by newly installed dependencies, not by upgrading
already installed ones. Transferred Gantt views identify installations whose
booking timeline must retain its Python and JavaScript adapter. This also repairs
databases that already completed the Calendar 2.1 ownership transfer.
"""


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT 1 FROM ir_model_data
         WHERE module = 'calendar_gantt' AND model = 'ir.ui.view'
         LIMIT 1
    """)
    if not cr.fetchone():
        return
    cr.execute("""
        UPDATE ir_module_module SET state = 'to install'
         WHERE name = 'calendar_gantt' AND state = 'uninstalled'
           AND EXISTS (
               SELECT 1 FROM ir_module_module
                WHERE name = 'web_gantt' AND state IN ('installed', 'to upgrade')
           )
    """)
    cr.execute("""
        UPDATE ir_module_module SET state = 'to install'
         WHERE name = 'calendar_gantt_hr' AND state = 'uninstalled'
           AND EXISTS (
               SELECT 1 FROM ir_module_module
                WHERE name = 'calendar_gantt'
                  AND state IN ('installed', 'to upgrade', 'to install')
           )
           AND EXISTS (
               SELECT 1 FROM ir_module_module
                WHERE name = 'appointment_hr' AND state IN ('installed', 'to upgrade')
           )
    """)
