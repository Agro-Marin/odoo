from odoo.db.schema import column_exists
from odoo.libs.parse_version import parse_version


def migrate(cr, version):
    if not version:
        return
    cr.execute("SELECT db_version FROM ir_module_module WHERE name = 'appointment'")
    installed = cr.fetchone()
    if not installed or parse_version(installed[0]) >= parse_version("19.0.1.4"):
        return
    if column_exists(cr, "appointment_resource", "capacity"):
        cr.execute("""
            UPDATE resource_resource r
               SET capacity = a.capacity
              FROM appointment_resource a
             WHERE a.resource_id = r.id
               AND a.capacity >= 1
               AND r.capacity IS DISTINCT FROM a.capacity
        """)
