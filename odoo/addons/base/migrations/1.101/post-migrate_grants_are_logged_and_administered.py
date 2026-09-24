"""The authorization log records the memberships 1.101 turned into grants, and
every group without an admin group is administered by the access
administrators (base.group_erp_manager). Both are idempotent.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        INSERT INTO ir_access_log (
            event, cause, count, actor_id,
            create_uid, write_uid, create_date, write_date
        )
        SELECT 'grant_migrated', 'migration', count(*), 1,
               1, 1, now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC'
          FROM res_users_grant
         WHERE cause = 'migration'
        HAVING count(*) > 0
           AND NOT EXISTS (
                SELECT 1 FROM ir_access_log WHERE event = 'grant_migrated'
               )
        """
    )
    cr.execute(
        """
        UPDATE res_groups
           SET admin_group_id = data.res_id
          FROM ir_model_data data
         WHERE data.module = 'base'
           AND data.name = 'group_erp_manager'
           AND data.model = 'res.groups'
           AND res_groups.admin_group_id IS NULL
        """
    )
    _logger.info(
        "base 1.101: %s groups are administered by the access administrators",
        cr.rowcount,
    )
