"""Archive the live memberships whose team or salesperson is already archived.

``crm.team.member._constrains_live_endpoints`` refuses these from now on, but a
constraint only fires on write: a database upgraded from an earlier version can
still hold rows the old code allowed -- joining an archived team, unarchiving
onto an archived salesperson, or archiving either endpoint back when neither
``crm.team.write`` nor ``res.users.write`` cascaded.

They are not inert. Reading a many2many drops archived corecords while the
searches do not, so every one of these rows is a disagreement between
``crm.team.member_ids`` and ``search([('member_ids', ...)])``, between
``res.users.crm_team_ids`` and ``search([('crm_team_ids', ...)])``, and a
``res_users.sale_team_id`` column pinned to a dead record -- which crm's
pipeline action and sale_commission both consume. Forbidding new ones is not
enough; the existing ones have to be cleaned.

Straight SQL, and ``sale_team_id`` recomputed by hand rather than through the
ORM: loading these records would run the very constraint they violate.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        UPDATE crm_team_member m
           SET active = FALSE
          FROM crm_team t, res_users u
         WHERE m.crm_team_id = t.id
           AND m.user_id = u.id
           AND m.active
           AND NOT (t.active AND u.active)
     RETURNING m.id
        """
    )
    archived = cr.rowcount
    if not archived:
        return

    # Re-derive the stored main team: the oldest live membership, matching
    # res.users._compute_sale_team_id and crm.team.member._order.
    cr.execute(
        """
        WITH main AS (
            SELECT DISTINCT ON (m.user_id) m.user_id, m.crm_team_id
              FROM crm_team_member m
             WHERE m.active
             ORDER BY m.user_id, m.create_date ASC, m.id
        )
        UPDATE res_users u
           SET sale_team_id = main.crm_team_id
          FROM main
         WHERE u.id = main.user_id
           AND u.sale_team_id IS DISTINCT FROM main.crm_team_id
        """
    )
    repointed = cr.rowcount

    cr.execute(
        """
        UPDATE res_users u
           SET sale_team_id = NULL
         WHERE u.sale_team_id IS NOT NULL
           AND NOT EXISTS (SELECT 1
                             FROM crm_team_member m
                            WHERE m.user_id = u.id
                              AND m.active)
        """
    )
    cleared = cr.rowcount

    _logger.info(
        "sales_team: archived %s membership(s) pointing at an archived team or "
        "salesperson; re-pointed %s and cleared %s res_users.sale_team_id",
        archived, repointed, cleared,
    )
