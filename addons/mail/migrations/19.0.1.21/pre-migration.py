"""Pre-migration for the volume-setting guest_id retarget (1.21).

``res.users.settings.volumes.guest_id`` was re-pointed from res.partner to
mail.guest (commit a3a5e15f) without a data migration. The column always
held mail.guest ids (callers pass guest ids; that mismatch was the bug being
fixed), but under the old FK a guest's deletion did not cascade here — the
constraint watched res_partner — so a database can hold rows whose guest_id
no longer exists in mail_guest. Those orphans make the ORM's creation of the
new FK fail during ``-u mail``, aborting the upgrade.

Drop the orphans before the schema update; a volume row for a deleted guest
is meaningless (the new FK cascades exactly these away going forward).

Idempotent: matches nothing once the orphans are gone.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        DELETE FROM res_users_settings_volumes v
         WHERE v.guest_id IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM mail_guest g WHERE g.id = v.guest_id)
        """
    )
    if cr.rowcount:
        _logger.info(
            "mail 1.21: removed %d volume setting(s) pointing at deleted guests.",
            cr.rowcount,
        )
