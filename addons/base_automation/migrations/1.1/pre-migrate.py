"""Drop cross-automation DAG edges before the constraint that forbids them (1.1).

``ir.actions.server._check_predecessors_scope`` now rejects a ``predecessor_ids``
entry whose ``base_automation_id`` differs from the action's own. Such an edge was
previously accepted and then silently discarded when the run was built, which left
the dependent step ``waiting`` with nothing that could ever complete it — the run
wedged in ``in_progress`` forever, with no error and nothing executed.

Any database carrying one of those edges would fail to upgrade, because the
constraint is validated against existing rows. They never did anything except
break the run they appeared in, so they are deleted rather than migrated, and each
one is logged so the administrator can see which automations were affected.

Idempotent: after the delete there is nothing left to match.
"""

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
         WHERE succ.base_automation_id IS DISTINCT FROM pred.base_automation_id
        """
    )
    offending = cr.fetchall()
    if not offending:
        return

    for successor_id, successor_name, predecessor_id, predecessor_name in offending:
        _logger.warning(
            "base_automation: dropping cross-automation dependency "
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
                AND succ.base_automation_id IS DISTINCT FROM pred.base_automation_id
        """
    )
    _logger.warning(
        "base_automation: removed %s unsatisfiable workflow dependency edge(s).",
        len(offending),
    )
