import logging

from odoo import SUPERUSER_ID, api
from odoo.tools import SQL

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Grant the Decider group to everyone who decides or may be asked to.

    The documents' read rows for approvers are on that group, and step
    membership and delegation grant it from now on: a person already deciding
    a pending request, or named on a step, keeps reading what they decide.
    """
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    rows = env.execute_query(
        SQL(
            """
            SELECT person.id
              FROM approval_approver row
              JOIN approval_request request ON request.id = row.request_id
              JOIN res_users person
                ON person.id IN (row.user_id, row.delegate_id)
             WHERE request.state = 'pending'
               AND row.state IN ('pending', 'waiting')
            UNION
            SELECT member.user_id FROM approval_category_step_member member
            """
        )
    )
    users = (
        env["res.users"]
        .with_context(active_test=False)
        .browse(sorted(user_id for (user_id,) in rows))
        .filtered(lambda user: not user.share)
    )
    grants = env["res.users.grant"]._grant(
        users,
        env.ref("approval.group_approval_decider"),
        cause="migration",
        reason="Decides or may be asked to decide an approval request",
    )
    for grant in grants:
        _logger.info(
            "approval 19.0.2.12.0: %s (%s) decides or may be asked to, and holds "
            "the Decider group now.",
            grant.user_id.login,
            grant.user_id.id,
        )
    _logger.info(
        "approval 19.0.2.12.0: %s approver(s) granted the Decider group.", len(grants)
    )
