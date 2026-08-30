import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        SELECT rel.successor_id,
               succ.name -> 'en_US',
               rel.predecessor_id,
               pred.name -> 'en_US'
          FROM ir_action_server_dependency_rel rel
          JOIN ir_act_server succ ON succ.id = rel.successor_id
          JOIN ir_act_server pred ON pred.id = rel.predecessor_id
         WHERE succ.automation_rule_id IS DISTINCT FROM pred.automation_rule_id
        """
    )
    offending = cr.fetchall()
    if not offending:
        return

    for successor_id, successor_name, predecessor_id, predecessor_name in offending:
        _logger.warning(
            "automation: dropping cross-automation dependency "
            "%s (#%s) -> %s (#%s); it could never complete and wedged the run.",
            predecessor_name,
            predecessor_id,
            successor_name,
            successor_id,
        )

    cr.execute(
        """
        DELETE FROM ir_action_server_dependency_rel rel
              USING ir_act_server succ, ir_act_server pred
              WHERE succ.id = rel.successor_id
                AND pred.id = rel.predecessor_id
                AND succ.automation_rule_id IS DISTINCT FROM pred.automation_rule_id
        """
    )
    _logger.warning(
        "automation: removed %s unsatisfiable workflow dependency edge(s).",
        len(offending),
    )
