r"""Pre-migration: merge hr.employee.category into res.partner.category.

The two models were one vocabulary written twice --
``hr.employee.category`` inherits ``mixin.tag``, ``res.partner.category`` became
``mixin.tag.nested`` in the same commit -- so this moves the rows and repoints the
join table rather than adding a second tag concept.

It matches on ``code``, not on ``name``. That is the whole reason step 1 came
first: ``code`` is non-translated and unique, while ``name`` is a jsonb
translation and two databases in different languages would match differently.

PRE rather than post, because ``hr.employee.category_ids`` now names
``res.partner.category``: the ORM would otherwise try to reconcile a foreign key
pointing at a table this migration has not yet emptied.

Every statement is idempotent -- an already-remapped row matches nothing on the
second pass.
"""

import logging

from odoo.tools import SQL

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute("SELECT to_regclass('hr_employee_category')")
    if not cr.fetchone()[0]:
        _logger.info("hr_employee_category is already gone; nothing to merge.")
        return

    # base migrates before hr, and base may rename res_partner_category to
    # res_partner_tag underneath this script. Resolve the table rather than
    # naming it, so this works on a database upgraded before that rename and on
    # one upgraded after.
    #
    # res_partner_category is checked FIRST, and the order is load-bearing.
    # website_customer shipped its own res.partner.tag -- the published label on
    # the customer references page -- so on a database carrying that module the
    # name res_partner_tag exists and holds WEBSITE tags. Preferring it would
    # merge employee tags into the website vocabulary and repoint
    # employee_category_rel at its ids. Checking res_partner_category first is
    # unambiguous instead of merely likely: base's rename removes that name, so
    # its presence means the rename has not run, and its absence means it has --
    # by which point res_partner_tag is base's, website_customer's copy having
    # been relocated to res_partner_website_tag by the same migration.
    cr.execute(
        """
        SELECT coalesce(to_regclass('res_partner_category'),
                        to_regclass('res_partner_tag'))::text
        """
    )
    partner_tags = cr.fetchone()[0]
    if not partner_tags:
        raise ValueError(
            "Neither res_partner_tag nor res_partner_category exists, so "
            "employee tags have nowhere to merge into. This migration will not "
            "guess; restore the partner tag table and run the upgrade again."
        )
    _logger.info("Merging employee tags into %s.", partner_tags)

    # The merge matches on `code`, which base adds to the partner tag model when
    # it adopts mixin.tag.nested. base migrates before hr -- but only when base
    # is ALSO being upgraded, and `-u hr` alone is a legitimate thing to run. On
    # a database where base has not caught up the column is simply absent, and
    # without it there is no key to match on: names are translated jsonb and two
    # databases in different languages would match differently.
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
         WHERE table_name = %s AND column_name = 'code'
        """,
        (partner_tags,),
    )
    if not cr.fetchone():
        raise ValueError(
            f"{partner_tags} has no `code` column, so base has not yet adopted "
            "mixin.tag.nested and employee tags have no key to merge on. Upgrade "
            "base in the same run -- `-u base,hr` -- and this will proceed. It is "
            "refused rather than matched on `name`, which is translated."
        )

    # Employee tags whose code no partner tag carries yet become partner tags.
    tags = SQL.identifier(partner_tags)
    cr.execute(
        SQL(
            """
            INSERT INTO %s (name, code, color, active, parent_path,
                            create_uid, write_uid, create_date, write_date)
            SELECT e.name, e.code, e.color, e.active, '', 1, 1, now(), now()
              FROM hr_employee_category e
             WHERE e.code IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM %s p WHERE p.code = e.code)
            """,
            tags,
            tags,
        )
    )
    created = cr.rowcount

    # Do NOT remap in place. Mid-migration `category_id` holds ids from two
    # independent sequences -- hr_employee_category's and
    # res_partner_category's -- so an UPDATE collides with rows it has not
    # reached yet whenever a new partner-tag id equals an old employee-tag id,
    # and the primary key is (employee_id, category_id). Measured: it drops a
    # tag the employee still holds, silently, and then fails on the next row.
    #
    # Build the whole target set first, delete every employee-tag link, then
    # insert. ON CONFLICT absorbs the employees who already held the merged tag.
    cr.execute(
        SQL(
            """
            CREATE TEMP TABLE _hr_tag_merge AS
            SELECT DISTINCT rel.employee_id, p.id AS category_id
              FROM employee_category_rel rel
              JOIN hr_employee_category e ON e.id = rel.category_id
              JOIN %s p ON p.code = e.code
            """,
            tags,
        )
    )
    cr.execute("SELECT count(*) FROM _hr_tag_merge")
    wanted = cr.fetchone()[0]

    cr.execute(
        """
        DELETE FROM employee_category_rel rel
         USING hr_employee_category e
         WHERE rel.category_id = e.id
        """
    )

    _repoint_link_foreign_key(cr, partner_tags)

    cr.execute(
        """
        INSERT INTO employee_category_rel (employee_id, category_id)
        SELECT employee_id, category_id FROM _hr_tag_merge
        ON CONFLICT DO NOTHING
        """
    )
    relinked = cr.rowcount
    collapsed = wanted - relinked
    cr.execute("DROP TABLE _hr_tag_merge")

    cr.execute(
        SQL(
            """
            SELECT count(*) FROM employee_category_rel rel
             WHERE NOT EXISTS (SELECT 1 FROM %s p WHERE p.id = rel.category_id)
            """,
            tags,
        )
    )
    orphans = cr.fetchone()[0]
    if orphans:
        # A tag with no code cannot be matched, and dropping the link would lose
        # data silently. Leave the row and say so.
        _logger.warning(
            "%s employee-tag link(s) point at a tag with no code and were left "
            "in place; they will not resolve until their tag is given one.",
            orphans,
        )
    else:
        cr.execute("DROP TABLE hr_employee_category CASCADE")
        cr.execute("DELETE FROM ir_model_data WHERE model = 'hr.employee.category'")

    _logger.info(
        "Employee tags: %s partner tag(s) created, %s link(s) repointed, "
        "%s already held the merged tag.",
        created,
        relinked,
        collapsed,
    )


def _repoint_link_foreign_key(cr, partner_tags):
    """Point ``employee_category_rel.category_id`` at the merged tag table.

    The column's FOREIGN KEY still names ``hr_employee_category``, so inserting
    a partner tag id into it raises ForeignKeyViolation and the merge cannot
    land -- the constraint describes exactly the table this migration exists to
    move away from. Waiting for the ORM does not help: 1.6 renames the table and
    the column, and Postgres carries a constraint's target across both.

    Called with the link table already emptied, so the replacement validates
    against no rows. Idempotent: a re-run finds the key already pointing at the
    tag table and does nothing.
    """
    cr.execute(
        """
        SELECT conname, confrelid::regclass::text
          FROM pg_constraint
         WHERE conrelid = 'employee_category_rel'::regclass AND contype = 'f'
           AND conkey = ARRAY[(
                SELECT attnum FROM pg_attribute
                 WHERE attrelid = 'employee_category_rel'::regclass
                   AND attname = 'category_id')]
        """
    )
    existing = cr.fetchall()
    if any(target == partner_tags for _, target in existing):
        return

    for conname, _target in existing:
        cr.execute(
            SQL(
                "ALTER TABLE employee_category_rel DROP CONSTRAINT %s",
                SQL.identifier(conname),
            )
        )
    cr.execute(
        SQL(
            "ALTER TABLE employee_category_rel ADD CONSTRAINT %s "
            "FOREIGN KEY (category_id) REFERENCES %s(id) ON DELETE CASCADE",
            SQL.identifier("employee_category_rel_category_id_fkey"),
            SQL.identifier(partner_tags),
        )
    )
    _logger.info("employee_category_rel.category_id now references %s.", partner_tags)
