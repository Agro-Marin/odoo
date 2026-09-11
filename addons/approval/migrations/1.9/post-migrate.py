import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # mail_activity.approver_id was inferred from an activity on the request with the
    # approval type; it is stored now. Link each such activity to the row of the user
    # it asks, the row's own user or its delegate, the lowest row first.
    cr.execute(
        """
        UPDATE mail_activity activity
           SET approver_id = match.approver_id
          FROM (
                SELECT DISTINCT ON (act.id) act.id AS activity_id,
                       approver.id AS approver_id
                  FROM mail_activity act
                  JOIN ir_model model ON model.id = act.res_model_id
                  JOIN ir_model_data xmlid
                    ON xmlid.module = 'approval'
                   AND xmlid.name = 'mail_activity_data_approval'
                   AND xmlid.res_id = act.activity_type_id
                  JOIN approval_approver approver
                    ON approver.request_id = act.res_id
                   AND act.user_id IN (approver.user_id, approver.delegate_id)
                 WHERE model.model = 'approval.request'
                   AND act.approver_id IS NULL
                 ORDER BY act.id, approver.id
               ) match
         WHERE activity.id = match.activity_id
        """,
    )
    if cr.rowcount:
        _logger.info(
            "approval 19.0.1.9.0: %d approval activit(ies) linked to their approver row.",
            cr.rowcount,
        )
