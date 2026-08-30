import logging

_logger = logging.getLogger(__name__)


def _table_exists(cr, name):
    cr.execute("SELECT to_regclass(%s)", (f"public.{name}",))
    return cr.fetchone()[0] is not None


def _migrate_definition_edges(cr):
    if not _table_exists(cr, "ir_action_server_dependency_rel"):
        return 0
    cr.execute(
        """
        INSERT INTO workflow_edge
            (source_node_id, target_node_id, automation_rule_id, condition,
             create_uid, create_date, write_uid, write_date)
        SELECT rel.predecessor_id, rel.successor_id, src.automation_rule_id,
               'on_success', 1, now(), 1, now()
          FROM ir_action_server_dependency_rel rel
          JOIN ir_act_server src ON src.id = rel.predecessor_id
          JOIN ir_act_server tgt ON tgt.id = rel.successor_id
         WHERE rel.predecessor_id != rel.successor_id
        ON CONFLICT DO NOTHING
        """
    )
    moved = cr.rowcount
    cr.execute("DROP TABLE ir_action_server_dependency_rel")
    return moved


def _migrate_runtime_edges(cr):
    if not _table_exists(cr, "automation_runtime_line_dag"):
        return 0
    cr.execute(
        """
        INSERT INTO automation_runtime_edge
            (runtime_id, source_line_id, target_line_id, condition,
             create_uid, create_date, write_uid, write_date)
        SELECT src.runtime_id, rel.predecessor_id, rel.successor_id,
               'on_success', 1, now(), 1, now()
          FROM automation_runtime_line_dag rel
          JOIN automation_runtime_line src ON src.id = rel.predecessor_id
          JOIN automation_runtime_line tgt ON tgt.id = rel.successor_id
         WHERE rel.predecessor_id != rel.successor_id
           AND src.runtime_id = tgt.runtime_id
        ON CONFLICT DO NOTHING
        """
    )
    moved = cr.rowcount
    cr.execute("DROP TABLE automation_runtime_line_dag")
    return moved


def migrate(cr, version):
    if not version:
        return

    definition_edges = _migrate_definition_edges(cr)
    runtime_edges = _migrate_runtime_edges(cr)
    _logger.info(
        "automation 1.6: migrated %s definition edge(s) and %s runtime edge(s) "
        "to the typed edge models, all as 'on_success'.",
        definition_edges,
        runtime_edges,
    )
