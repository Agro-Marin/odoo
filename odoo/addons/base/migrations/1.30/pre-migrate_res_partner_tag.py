r"""Pre-migration: rename ``res.partner.category`` to ``res.partner.tag``.

The model was a tag in everything except its name. It inherits
``mixin.tag.nested``, describes itself as a tag, labels its own reverse field
"Child Tags", and ``res.partner`` presents it as "Tags" -- while its three
sibling nested tags (``tag.tag``, ``crm.tag``, ``srm.tag``) all agree on
``*.tag``. ADR-0086 step 6 then merged ``hr.employee.category`` into it, so
"partner category" stopped describing either half of the vocabulary it holds.

THE TARGET NAME WAS OCCUPIED, AND ON EXISTING DATABASES IT STILL IS.
``website_customer`` defines its own ``res.partner.tag`` -- the published label
on the customer references page, which despite the name adopts no tag mixin and
carries no ``code``. It is relocated to ``res.partner.website.tag``, and that
relocation has to happen HERE, first, rather than in ``website_customer``'s own
migration: ``base`` is migrated before the module graph is extended, so by the
time ``website_customer`` ran, ``base`` would already have tried to create
``res_partner_tag`` on top of it. Measured: without this step the rename aborts
on any database with ``website_customer`` installed.

PRE rather than post, because the ORM must never see either new model with no
table. ``_auto_init`` would create an empty one beside the populated old one and
every tag on every partner would be gone with no error -- the old table would
simply stop being read.

EVERY DERIVED MANY2MANY TABLE MOVES, NOT JUST THE PARTNER ONE. A Many2many that
declares no ``relation=`` gets ``"_".join(sorted([table1, table2])) + "_rel"``
(``fields/relational/many2many.py``), so renaming one side renames the join
table. Measured on this workspace: three of them for the tag model --
``res.partner.category_id`` plus ``mailing.contact.tag_ids`` and
``loyalty.generate.wizard.customer_tag_ids`` -- and the set depends on which
modules a database has installed, which a hardcoded list cannot know. So the
names are recomputed with the ORM's own rule rather than string-substituted:
``sorted()`` can REORDER the two halves (``res_partner_category`` sorts before
``res_partner_industry``, ``res_partner_tag`` after it), and a substitution would
silently produce a name the registry then fails to find.

CONSTRAINTS AND INDEXES ARE RENAMED BY PREFIX, NOT FROM A LIST, for the same
reason. Postgres keeps a constraint's name when its table is renamed, and the
constraint set is not fixed: ``agromarin``'s ``is_exclusive`` and
``scoring_active`` add their own NOT NULL constraints named after the table, and
a list written against a stock database would leave them behind for the ORM to
reconcile against a table that no longer answers to that name.

THIS UPGRADE NEEDS ``-u base``, NOT A PER-MODULE ``-u``. A module's pre-migration
runs only when its state is "to upgrade" (``modules/loading.py``,
``update_operation``), and a version bump alone does not mark base. Measured:
``-u partner`` on a database still at base 19.0.1.25 ran no base migration, left
``res_partner_category`` in place, and died with ParseError on
``base.action_partner_tag_form`` — loudly, but only after other pre-migrations
had already committed. Upgrade base, or upgrade everything.

WHAT THIS DELIBERATELY LEAVES BEHIND: on an upgraded database, the auto-generated
FOREIGN KEY, NOT NULL and index names on the join tables keep the old word --
``mailing_contact_res_partner_catego_res_partner_category_id_fkey`` and eight
others measured here. Postgres truncates a generated name to 63 characters, so
they no longer carry the join table's full name as a prefix and cannot be
renamed by prefix like the rest. They are inert: the ORM reconciles a foreign key
by table and column, never by constraint name. Verified by upgrading base plus
base_order, mass_mailing, loyalty, website_customer and partner together -- exit
0, no duplicate table created, every row count unchanged. A fresh install carries
the correct names; this residue exists only where a database was upgraded.

RECORD EXTERNAL IDS ARE DELIBERATELY NOT RENAMED. ``base.res_partner_category_14``
and its siblings name individual tag *rows*, and an external id is the key every
database joins its own data on; renaming them orphans rows that a later
``_process_end`` then deletes. Only ``ir_model_data.model`` moves for those. The
ids that are renamed are the ones naming the *model* -- ``ir.model``,
``ir.model.fields``, ``ir.model.constraint``, ``ir.model.inherit``,
``ir.model.access`` -- and the views, action and rule that exist to serve it,
which are recreated from the renamed source on the same upgrade.

``employee_category_rel`` and the ``category_id`` columns keep their names: they
are named after the FIELD (``res.partner.category_id``,
``hr.employee.category_ids``), which this change does not rename. A field rename
is a separate decision with a much larger consumer surface.

Every statement is idempotent -- each guard stops matching once the rename has
happened, so a re-run finds nothing to do.
"""

import logging
import typing

from odoo.db import schema
from odoo.tools import SQL

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)

WEBSITE_OLD_MODEL = "res.partner.tag"
WEBSITE_NEW_MODEL = "res.partner.website.tag"
WEBSITE_OLD_TABLE = "res_partner_tag"
WEBSITE_NEW_TABLE = "res_partner_website_tag"

TAG_OLD_MODEL = "res.partner.category"
TAG_NEW_MODEL = "res.partner.tag"
TAG_OLD_TABLE = "res_partner_category"
TAG_NEW_TABLE = "res_partner_tag"

# ir_model_data rows naming a model's views, action or rule rather than a row.
WEBSITE_XMLIDS = (
    (
        "ir.rule",
        "website_customer_res_partner_tag_public",
        "website_customer_res_partner_website_tag_public",
    ),
)
TAG_XMLIDS = (
    (
        "ir.actions.act_window",
        "action_partner_category_form",
        "action_partner_tag_form",
    ),
    ("ir.ui.view", "res_partner_category_view_search", "res_partner_tag_view_search"),
    ("ir.ui.view", "view_partner_category_form", "view_partner_tag_form"),
    ("ir.ui.view", "view_partner_category_list", "view_partner_tag_list"),
)

STRUCTURAL_MODELS = (
    "ir.model",
    "ir.model.fields",
    "ir.model.constraint",
    "ir.model.inherit",
    "ir.model.access",
)


def migrate(cr: Cursor, version: str) -> None:
    if not version:
        return

    _relocate_website_customer_tag(cr)

    if not schema.table_exists(cr, TAG_OLD_TABLE):
        _logger.info("%s is already gone; nothing to rename.", TAG_OLD_TABLE)
        return
    if schema.table_exists(cr, TAG_NEW_TABLE):
        raise ValueError(
            f"Both {TAG_OLD_TABLE} and {TAG_NEW_TABLE} exist and the second is "
            f"not website_customer's. Refusing to guess which holds the tags."
        )

    rels = _rename_model(
        cr, TAG_OLD_MODEL, TAG_NEW_MODEL, TAG_OLD_TABLE, TAG_NEW_TABLE, TAG_XMLIDS
    )
    _logger.info(
        "%s renamed to %s, with %d derived join table(s): %s",
        TAG_OLD_MODEL,
        TAG_NEW_MODEL,
        len(rels),
        ", ".join(f"{old} -> {new}" for old, new in rels.items()) or "none",
    )


def _relocate_website_customer_tag(cr: Cursor) -> None:
    """Move website_customer's res.partner.tag out of the name base is claiming."""
    cr.execute(
        """
        SELECT 1 FROM ir_model_data
         WHERE module = 'website_customer' AND model = 'ir.model'
           AND name = 'model_res_partner_tag'
        """
    )
    if not cr.fetchone():
        return
    if not schema.table_exists(cr, WEBSITE_OLD_TABLE):
        return

    # This one m2m declares its relation explicitly, so the derived-name rule
    # below cannot find it.
    _rename_table_if_present(
        cr, "res_partner_res_partner_tag_rel", "res_partner_res_partner_website_tag_rel"
    )
    cr.execute(
        "UPDATE ir_model_fields SET relation_table = %s WHERE relation_table = %s",
        ("res_partner_res_partner_website_tag_rel", "res_partner_res_partner_tag_rel"),
    )
    cr.execute(
        "UPDATE ir_model_relation SET name = %s WHERE name = %s",
        ("res_partner_res_partner_website_tag_rel", "res_partner_res_partner_tag_rel"),
    )

    _rename_model(
        cr,
        WEBSITE_OLD_MODEL,
        WEBSITE_NEW_MODEL,
        WEBSITE_OLD_TABLE,
        WEBSITE_NEW_TABLE,
        WEBSITE_XMLIDS,
    )
    _logger.info(
        "website_customer's %s relocated to %s, freeing the name for base.",
        WEBSITE_OLD_MODEL,
        WEBSITE_NEW_MODEL,
    )


def _rename_model(
    cr: Cursor,
    old_model: str,
    new_model: str,
    old_table: str,
    new_table: str,
    xmlids: tuple,
) -> dict[str, str]:
    _rename_table_if_present(cr, old_table, new_table)
    _rename_sequence(cr, old_table, new_table)
    rels = _rename_derived_relations(cr, old_model, old_table, new_table)
    _rewrite_registry_rows(cr, old_model, new_model, old_table, new_table, rels, xmlids)
    return rels


def _rename_table_if_present(cr: Cursor, old: str, new: str) -> None:
    if not schema.table_exists(cr, old) or schema.table_exists(cr, new):
        return
    cr.execute(
        SQL("ALTER TABLE %s RENAME TO %s", SQL.identifier(old), SQL.identifier(new))
    )
    # Renaming a UNIQUE or PRIMARY KEY constraint renames its backing index too,
    # so constraints go first and whatever still carries the old prefix after
    # that is a plain index.
    cr.execute(
        "SELECT conname FROM pg_constraint "
        "WHERE conrelid = %s::regclass AND conname LIKE %s",
        (new, old + "\\_%"),
    )
    for (conname,) in cr.fetchall():
        cr.execute(
            SQL(
                "ALTER TABLE %s RENAME CONSTRAINT %s TO %s",
                SQL.identifier(new),
                SQL.identifier(conname),
                SQL.identifier(new + conname[len(old) :]),
            )
        )
    cr.execute(
        "SELECT indexname FROM pg_indexes WHERE tablename = %s AND indexname LIKE %s",
        (new, old + "\\_%"),
    )
    for (indexname,) in cr.fetchall():
        cr.execute(
            SQL(
                "ALTER INDEX %s RENAME TO %s",
                SQL.identifier(indexname),
                SQL.identifier(new + indexname[len(old) :]),
            )
        )


def _rename_sequence(cr: Cursor, old_table: str, new_table: str) -> None:
    # ALTER TABLE ... RENAME leaves the owned sequence under its old name.
    cr.execute(
        "SELECT 1 FROM pg_sequences WHERE sequencename = %s", (old_table + "_id_seq",)
    )
    if cr.fetchone():
        cr.execute(
            SQL(
                "ALTER SEQUENCE %s RENAME TO %s",
                SQL.identifier(old_table + "_id_seq"),
                SQL.identifier(new_table + "_id_seq"),
            )
        )


def _derived_relation(table_a: str, table_b: str) -> str:
    return "_".join(sorted([table_a, table_b])) + "_rel"


def _rename_derived_relations(
    cr: Cursor, old_model: str, old_table: str, new_table: str
) -> dict[str, str]:
    """Rename every derived join table the model takes part in, BOTH directions.

    A Many2many can point AT the renamed model or live ON it. ``base_order``
    gives the second shape: ``res.partner.category.group_ids`` has
    ``relation = 'res.groups'``, so a query filtered on ``relation`` alone never
    sees ``res_groups_res_partner_category_rel`` -- and the reloaded registry
    then derives ``res_groups_res_partner_tag_rel``, creates it EMPTY, and every
    order restriction is silently gone.
    """
    cr.execute(
        """
        SELECT model, relation, relation_table FROM ir_model_fields
         WHERE ttype = 'many2many' AND relation_table IS NOT NULL
           AND (model = %s OR relation = %s)
        """,
        (old_model, old_model),
    )
    renamed: dict[str, str] = {}
    for model, relation, relation_table in cr.fetchall():
        own_table = model.replace(".", "_")
        co_table = relation.replace(".", "_")
        if relation_table != _derived_relation(own_table, co_table):
            # An explicit relation= the derived rule does not reach, such as
            # hr's employee_category_rel.
            continue
        pair = [new_table if t == old_table else t for t in (own_table, co_table)]
        new_relation = _derived_relation(*pair)
        if relation_table in renamed or not schema.table_exists(cr, relation_table):
            continue
        if schema.table_exists(cr, new_relation):
            raise ValueError(
                f"Both {relation_table} and {new_relation} exist. Refusing to "
                f"guess which one holds the links; resolve by hand."
            )
        _rename_table_if_present(cr, relation_table, new_relation)
        _rename_derived_column(cr, new_relation, old_table, new_table)
        renamed[relation_table] = new_relation
    return renamed


def _rename_derived_column(
    cr: Cursor, relation_table: str, old_table: str, new_table: str
) -> None:
    """Move the join column the ORM derives from the model's table name.

    ``column2`` defaults to ``f"{comodel._table}_id"``, so a join table that
    named no columns carries ``res_partner_category_id`` and the reloaded
    registry looks for ``res_partner_tag_id``. Measured: without this the
    upgrade dies in ``check_foreign_keys`` with UndefinedColumn, *after* the
    tables have already moved.
    """
    old_column = old_table + "_id"
    new_column = new_table + "_id"
    if not schema.column_exists(cr, relation_table, old_column):
        return
    if schema.column_exists(cr, relation_table, new_column):
        return
    cr.execute(
        SQL(
            "ALTER TABLE %s RENAME COLUMN %s TO %s",
            SQL.identifier(relation_table),
            SQL.identifier(old_column),
            SQL.identifier(new_column),
        )
    )
    # Both ends of the relation record the column, and the reverse field lives
    # on the renamed model itself, so match on the table rather than the field.
    cr.execute(
        "UPDATE ir_model_fields SET column1 = %s "
        "WHERE relation_table = %s AND column1 = %s",
        (new_column, relation_table, old_column),
    )
    cr.execute(
        "UPDATE ir_model_fields SET column2 = %s "
        "WHERE relation_table = %s AND column2 = %s",
        (new_column, relation_table, old_column),
    )


def _rewrite_registry_rows(
    cr: Cursor,
    old_model: str,
    new_model: str,
    old_table: str,
    new_table: str,
    renamed_rels: dict[str, str],
    xmlids: tuple,
) -> None:
    cr.execute(
        "UPDATE ir_model SET model = %s WHERE model = %s", (new_model, old_model)
    )
    cr.execute(
        "UPDATE ir_model_fields SET model = %s WHERE model = %s", (new_model, old_model)
    )
    cr.execute(
        "UPDATE ir_model_fields SET relation = %s WHERE relation = %s",
        (new_model, old_model),
    )
    for old, new in renamed_rels.items():
        cr.execute(
            "UPDATE ir_model_fields SET relation_table = %s WHERE relation_table = %s",
            (new, old),
        )
        cr.execute("UPDATE ir_model_relation SET name = %s WHERE name = %s", (new, old))
    cr.execute(
        "UPDATE ir_ui_view SET model = %s WHERE model = %s", (new_model, old_model)
    )
    cr.execute(
        "UPDATE ir_act_window SET res_model = %s WHERE res_model = %s",
        (new_model, old_model),
    )
    cr.execute(
        "UPDATE ir_model_constraint SET name = replace(name, %s, %s) WHERE name LIKE %s",
        (old_table, new_table, "%" + old_table + "%"),
    )

    # The rows themselves: their external ids keep their historical spelling,
    # only the model they point at moves.
    cr.execute(
        "UPDATE ir_model_data SET model = %s WHERE model = %s", (new_model, old_model)
    )
    cr.execute(
        """
        UPDATE ir_model_data
           SET name = replace(name, %s, %s)
         WHERE model = ANY(%s) AND name LIKE %s
        """,
        (old_table, new_table, list(STRUCTURAL_MODELS), "%" + old_table + "%"),
    )
    for model, old, new in xmlids:
        cr.execute(
            "UPDATE ir_model_data SET name = %s WHERE model = %s AND name = %s",
            (new, model, old),
        )
