import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def _table_exists(cr, table):
    cr.execute("SELECT to_regclass(%s)", [table])
    return cr.fetchone()[0] is not None


def migrate(cr, version):
    if not _table_exists(cr, "project_role"):
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    field = env["project.task"]._fields["role_ids"]
    relation, task_column, role_column = field.relation, field.column1, field.column2

    cr.execute("SELECT count(*) FROM project_role")
    total = cr.fetchone()[0]

    cr.execute("ALTER TABLE resource_role ADD COLUMN _legacy_project_role_id integer")
    cr.execute("""
        INSERT INTO resource_role
               (name, active, color, sequence,
                create_uid, create_date, write_uid, write_date,
                _legacy_project_role_id)
        SELECT  name, active, color, sequence,
                create_uid, create_date, write_uid, write_date,
                id
          FROM project_role
    """)

    if _table_exists(cr, "project_role_project_task_rel"):
        cr.execute(f"""
            INSERT INTO {relation} ({task_column}, {role_column})
            SELECT rel.project_task_id, new_role.id
              FROM project_role_project_task_rel rel
              JOIN resource_role new_role
                ON new_role._legacy_project_role_id = rel.project_role_id
              JOIN project_task task
                ON task.id = rel.project_task_id
            ON CONFLICT DO NOTHING
        """)
        moved_links = cr.rowcount
        cr.execute("DROP TABLE project_role_project_task_rel")
    else:
        moved_links = 0

    cr.execute("ALTER TABLE resource_role DROP COLUMN _legacy_project_role_id")
    cr.execute("DROP TABLE project_role")

    _logger.info(
        "project 1.15: moved %d project.role record(s) and %d task link(s) "
        "onto resource.role.",
        total,
        moved_links,
    )
