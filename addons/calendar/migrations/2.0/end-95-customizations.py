"""Restore custom views after normal source-view writes invalidate their rows."""

from odoo.db.schema import table_exists


def migrate(cr, version):
    if not version or not table_exists(cr, "calendar_booking_upgrade_view_custom"):
        return
    cr.execute("""
        INSERT INTO ir_ui_view_custom
        SELECT * FROM calendar_booking_upgrade_view_custom
        ON CONFLICT (id) DO NOTHING
    """)
    cr.execute("DROP TABLE calendar_booking_upgrade_view_custom")
