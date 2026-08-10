"""Move `project.role` records onto the shared `resource.role`.

`project` and `planning` had each grown their own role model, field for field
-- name, active, colour, sequence -- so a role defined in one was invisible to
the other even when both meant the same person. `resource.role` is the shared
one, and it lives in `resource` because the question a role answers ("what can
this resource do") belongs to the resource rather than to whichever app asks.

`project.role` is the first to move; it has no other module extending it.

Two things have to travel, not just the rows:

- `project.task.role_ids` is a Many2many with no explicit relation, so its
  table name is derived from the two model tables. Repointing the comodel
  changes that name, and the ORM creates the new (empty) table on upgrade
  while the old one keeps every link. The relation's real name is read off
  the field rather than spelled out here, so this cannot drift from whatever
  the ORM actually built.
- The new ids differ from the old ones: `resource_role` has its own sequence
  and may already hold rows. A temporary column carries the old id across so
  the link table can be remapped, and is dropped again immediately.

`project.template.role.to.users.map` also points at the model, but it is a
TransientModel -- its rows are vacuumed, so there is nothing to migrate.

Idempotent: guarded on the legacy table still existing.
"""

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
    # `name` is translated on both sides, so it is jsonb on both and copies
    # across whole -- every language, not just the one this upgrade runs in.
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
