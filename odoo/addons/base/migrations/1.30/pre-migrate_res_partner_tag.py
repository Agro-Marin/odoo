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
