from odoo.tools.module_data import rename_in_stored_expressions

PHONE_HOLDERS = ("company", "company_id", "user_id", "event_organizer")
PRIMARY_NUMBER = "phone_ids._primary().number"


def migrate(cr, version):
    if not version:
        return

    for holder in PHONE_HOLDERS:
        rename_in_stored_expressions(
            cr, f"{holder}.phone", f"{holder}.{PRIMARY_NUMBER}"
        )
