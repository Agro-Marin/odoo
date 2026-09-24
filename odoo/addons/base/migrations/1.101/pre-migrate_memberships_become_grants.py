"""Every group membership becomes a grant (authorization plan P2, decision M1).

`res_groups_users_rel` is from now on the projection of the active grants.
Each of its rows gets one unscoped, open-ended grant whose cause is the
migration, the redundant ones included: a database upgraded from 17 or 18
keeps the implied groups as explicit rows (1 177 of the production copy's
1 685 active ones), and keeping them as grants keeps what revoking a group
does exactly as it was.

It runs before base's tables are updated, creating the grant table itself,
so that from the moment the table exists every membership has its grant: the
groups a user holds are read from the grants alone, and base's own data,
loaded next, would otherwise meet a table holding only what it grants.
A pair that already has a live grant is skipped, so a second run adds nothing.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        CREATE TABLE IF NOT EXISTS res_users_grant (
            id SERIAL NOT NULL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            state VARCHAR NOT NULL,
            cause VARCHAR NOT NULL,
            create_uid INTEGER,
            write_uid INTEGER,
            create_date TIMESTAMP,
            write_date TIMESTAMP
        )
        """
    )
    cr.execute(
        """
        INSERT INTO res_users_grant (
            user_id, group_id, state, cause,
            create_uid, write_uid, create_date, write_date
        )
        SELECT rel.uid, rel.gid, 'active', 'migration',
               1, 1, now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC'
          FROM res_groups_users_rel rel
         WHERE NOT EXISTS (
                SELECT 1
                  FROM res_users_grant grant_
                 WHERE grant_.user_id = rel.uid
                   AND grant_.group_id = rel.gid
                   AND grant_.state IN ('scheduled', 'active')
               )
        """
    )
    _logger.info("base 1.101: %s group memberships became grants", cr.rowcount)
