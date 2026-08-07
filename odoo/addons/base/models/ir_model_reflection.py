"""Schema-reflection bookkeeping models.

These models record the PostgreSQL schema objects (constraints, indexes and
many2many relation tables) that Odoo models create, so they can be dropped again
when the owning module is uninstalled. Split out of ``ir_model_access.py``, with
which they share no logic.
"""

import logging
from collections.abc import Collection
from typing import Any, Self

from psycopg.types.json import Json, Jsonb

from odoo import fields, models
from odoo.api import ValuesType
from odoo.db import schema as sql
from odoo.exceptions import AccessError
from odoo.libs.sql import make_identifier
from odoo.tools import SQL, OrderedSet
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)


class IrModelConstraint(models.Model):
    """Tracks PostgreSQL indexes, foreign keys and constraints used by Odoo models."""

    _name = "ir.model.constraint"
    _description = "Model Constraint"
    _allow_sudo_commands = False

    name = fields.Char(
        string="Constraint",
        required=True,
        index=True,
        readonly=True,
        help="PostgreSQL constraint or foreign key name.",
    )
    definition = fields.Char(help="PostgreSQL constraint definition", readonly=True)
    message = fields.Char(
        help="Error message returned when the constraint is violated.",
        translate=True,
    )
    model = fields.Many2one(
        "ir.model", required=True, ondelete="cascade", index=True, readonly=True
    )
    module = fields.Many2one(
        "ir.module.module",
        required=True,
        index=True,
        ondelete="cascade",
        readonly=True,
    )
    type = fields.Char(
        string="Constraint Type",
        required=True,
        size=1,
        readonly=True,
        help="Type of the constraint: `f` for a foreign key, `u` for other constraints.",
    )

    _module_name_uniq = models.Constraint(
        "UNIQUE (name, module)",
        "Constraints with the same name are unique per module.",
    )

    def unlink(self) -> bool:
        self.check_access("unlink")
        ids_set = set(self.ids)

        owners: dict[str, set[int]] = {}
        names = list({data.name for data in self})
        if names:
            owners = {
                name: set(ids)
                for name, ids in self.env.execute_query(
                    SQL(
                        "SELECT name, array_agg(id) FROM ir_model_constraint"
                        " WHERE name = ANY(%s) GROUP BY name",
                        names,
                    )
                )
            }

        for data in self.sorted(key="id", reverse=True):
            name = data.name
            if owners.get(name, set()) - ids_set:
                continue

            hname = make_identifier(name)
            typ = data.type
            if typ in ("f", "u"):
                # ask PostgreSQL which table carries the constraint instead of
                # deriving it from the model name: a model absent from the
                # registry (its module is being uninstalled -- exactly when this
                # runs) left only the `model.replace(".", "_")` guess, which is
                # wrong for every model with a custom _table, e.g. ir.actions.*
                for (table,) in self.env.execute_query(
                    SQL(
                        """SELECT cl.relname
                    FROM pg_constraint cs
                    JOIN pg_class cl
                    ON (cs.conrelid = cl.oid)
                    WHERE cs.contype = ANY(%s) AND cs.conname = %s
                    AND cl.relnamespace = current_schema::regnamespace
                    """,
                        ["c", "u", "x"] if typ == "u" else [typ],
                        hname,
                    )
                ):
                    self.env.execute_query(
                        SQL(
                            "ALTER TABLE %s DROP CONSTRAINT %s",
                            SQL.identifier(table),
                            SQL.identifier(hname),
                        )
                    )
                    _logger.info(
                        "Dropped CONSTRAINT %s@%s (table %s)",
                        name,
                        data.model.model,
                        table,
                    )

            elif typ == "i":
                self.env.execute_query(
                    SQL("DROP INDEX IF EXISTS %s", SQL.identifier(hname))
                )
                _logger.info("Dropped INDEX %s@%s", name, data.model.model)

        return super().unlink()

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        vals_list = super().copy_data(default=default)
        return [
            dict(vals, name=constraint.name + "_copy")
            for constraint, vals in zip(self, vals_list, strict=True)
        ]

    def _reflect_constraint(
        self,
        model: Any,
        conname: str,
        type: str,
        definition: str,
        module: str,
        message: str | None = None,
    ) -> Self | None:
        """Reflect the given constraint so it can be dropped when its module is
        uninstalled. ``type`` is 'f' (foreign key), 'i' (index) or 'u' (other).

        :return: the created/modified record, or ``None`` if unchanged
        """
        if not module:
            return None
        if type not in ("f", "u", "i"):
            raise ValueError(
                f"Invalid constraint type {type!r}: expected 'f', 'u', or 'i'."
            )
        rows = self.env.execute_query_dict(
            SQL(
                """SELECT c.id, type, definition, message->'en_US' as message
            FROM ir_model_constraint c, ir_module_module m
            WHERE c.module = m.id AND c.name = %s AND m.name = %s
            """,
                conname,
                module,
            )
        )
        if not rows:
            [[cons_id]] = self.env.execute_query(
                SQL(
                    """
                INSERT INTO ir_model_constraint
                    (name, create_date, write_date, create_uid, write_uid, module, model, type, definition, message)
                VALUES (%s,
                        now() AT TIME ZONE 'UTC',
                        now() AT TIME ZONE 'UTC',
                        %s, %s,
                        (SELECT id FROM ir_module_module WHERE name=%s),
                        (SELECT id FROM ir_model WHERE model=%s),
                        %s, %s, %s)
                RETURNING id
                """,
                    conname,
                    self.env.uid,
                    self.env.uid,
                    module,
                    model._name,
                    type,
                    definition,
                    Json({"en_US": message}),
                )
            )
            return self.browse(cons_id)
        [cons] = rows
        cons_id = cons.pop("id")
        if cons != {"type": type, "definition": definition, "message": message}:
            self.env.execute_query(
                SQL(
                    """
                UPDATE ir_model_constraint
                SET write_date=now() AT TIME ZONE 'UTC',
                    write_uid = %s, type = %s, definition = %s, message = %s
                WHERE id = %s""",
                    self.env.uid,
                    type,
                    definition,
                    Json({"en_US": message}),
                    cons_id,
                )
            )
            return self.browse(cons_id)
        return None

    def _reflect_constraints(self, model_names: list[str]) -> None:
        """Reflect the ``_table_objects`` of the given models.

        Batched like ``_reflect_fields``: one SELECT for all ``(name, module)``
        pairs, one MERGE for created/changed rows and one batched xml-id update,
        instead of a round-trip per constraint. MERGE (not ``INSERT ... ON
        CONFLICT``) so the upsert does not require the ``(name, module)`` unique
        constraint to already exist in the database.
        """
        expected: dict[tuple[str, str], dict[str, Any]] = {}
        for model_name in model_names:
            model = self.env[model_name]
            for conname, cons in model._table_objects.items():
                module = cons._module
                if not conname or not module:
                    _logger.warning("Missing module or constraint name for %s", cons)
                    continue
                message = cons.message
                if not isinstance(message, str) or not message:
                    message = None
                expected[(conname, module)] = {
                    "model": model_name,
                    "type": "i" if isinstance(cons, models.Index) else "u",
                    "definition": cons.get_definition(model.pool),
                    "message": message,
                }
        if not expected:
            return

        existing = {
            (name, module): row
            for name, module, *row in self.env.execute_query(
                SQL(
                    """SELECT c.name, m.name, c.type, c.definition,
                              c.message->>'en_US'
                       FROM ir_model_constraint c
                       JOIN ir_module_module m ON c.module = m.id
                       WHERE c.name = ANY(%s)""",
                    list({name for name, _module in expected}),
                )
            )
        }
        changed = {
            key: vals
            for key, vals in expected.items()
            if existing.get(key) != [vals["type"], vals["definition"], vals["message"]]
        }

        cons_ids: dict[tuple[str, str], int] = {}
        if changed:
            module_ids = dict(
                self.env.execute_query(
                    SQL(
                        "SELECT name, id FROM ir_module_module WHERE name = ANY(%s)",
                        list({module for _name, module in changed}),
                    )
                )
            )
            get_model_id = self.env["ir.model"]._get_id
            values = SQL(", ").join(
                SQL(
                    "(%s, %s, %s, %s, %s, %s)",
                    name,
                    module_ids[module],
                    get_model_id(vals["model"]),
                    vals["type"],
                    vals["definition"],
                    Jsonb({"en_US": vals["message"]}),
                )
                for (name, module), vals in changed.items()
            )
            result = self.env.execute_query(
                SQL(
                    """
                    MERGE INTO ir_model_constraint t
                    USING (VALUES %(values)s)
                        AS s(name, module, model, type, definition, message)
                    ON t.name = s.name AND t.module = s.module
                    WHEN MATCHED THEN
                        UPDATE SET write_date = now() AT TIME ZONE 'UTC',
                                   write_uid = %(uid)s,
                                   type = s.type,
                                   definition = s.definition,
                                   message = s.message
                    WHEN NOT MATCHED THEN
                        INSERT (name, module, model, type, definition, message,
                                create_date, write_date, create_uid, write_uid)
                        VALUES (s.name, s.module, s.model, s.type, s.definition,
                                s.message,
                                now() AT TIME ZONE 'UTC',
                                now() AT TIME ZONE 'UTC',
                                %(uid)s, %(uid)s)
                    RETURNING NEW.id, NEW.name, NEW.module
                    """,
                    values=values,
                    uid=self.env.uid,
                )
            )
            module_names = {mid: mname for mname, mid in module_ids.items()}
            cons_ids = {
                (name, module_names[module_id]): cons_id
                for cons_id, name, module_id in result
            }

        data_list = []
        for name, module in expected:
            xml_id = f"{module}.constraint_{name}"
            cons_id = cons_ids.get((name, module))
            if cons_id:
                data_list.append({"xml_id": xml_id, "record": self.browse(cons_id)})
            else:
                self.env["ir.model.data"]._load_xmlid(xml_id)
        if data_list:
            self.env["ir.model.data"]._update_xmlids(data_list)


class IrModelRelation(models.Model):
    """Tracks PostgreSQL tables implementing Odoo many2many relations."""

    _name = "ir.model.relation"
    _description = "Relation Model"
    _allow_sudo_commands = False

    name = fields.Char(
        string="Relation Name",
        required=True,
        index=True,
        help="PostgreSQL table name implementing a many2many relation.",
    )
    model = fields.Many2one("ir.model", required=True, index=True, ondelete="cascade")
    module = fields.Many2one(
        "ir.module.module", required=True, index=True, ondelete="cascade"
    )
    write_date = fields.Datetime()
    create_date = fields.Datetime()

    def _module_data_uninstall(self) -> None:
        """Delete PostgreSQL many2many relation tables tracked by this model."""
        if not self.env.is_system():
            raise AccessError(
                _("Administrator access is required to uninstall a module")
            )

        ids_set = set(self.ids)

        owners: dict[str, set[int]] = {}
        names = list({data.name for data in self})
        if names:
            owners = {
                name: set(ids)
                for name, ids in self.env.execute_query(
                    SQL(
                        "SELECT name, array_agg(id) FROM ir_model_relation"
                        " WHERE name = ANY(%s) GROUP BY name",
                        names,
                    )
                )
            }

        to_drop = OrderedSet()
        for data in self.sorted(key="id", reverse=True):
            name = data.name
            if not owners.get(name, set()).issubset(ids_set):
                continue
            if sql.table_exists(self.env.cr, name):
                to_drop.add(name)

        self.unlink()

        for table in to_drop:
            self.env.cr.execute(SQL("DROP TABLE %s CASCADE", SQL.identifier(table)))
            _logger.info("Dropped table %s", table)

    def _reflect_relations(self, items: Collection[tuple[str, str, str]]) -> None:
        """Reflect m2m tables so they can be dropped when their module is
        uninstalled. Each item is ``(model_name, table, module)``.

        Batched like every other reflector: one SELECT for all ``(name, module)``
        pairs and one INSERT for the missing rows.  It used to run a SELECT and
        possibly an INSERT *per many2many field*, redoing the work for every
        field sharing a relation table -- both sides of a relation always do.
        """
        expected: dict[tuple[str, str], str] = {}
        for model_name, table, module in items:
            expected.setdefault((table, module), model_name)
        if not expected:
            return

        existing = set(
            self.env.execute_query(
                SQL(
                    """SELECT r.name, m.name
                       FROM ir_model_relation r
                       JOIN ir_module_module m ON r.module = m.id
                       WHERE r.name = ANY(%s)""",
                    list({table for table, _module in expected}),
                )
            )
        )
        missing = {key: name for key, name in expected.items() if key not in existing}
        if not missing:
            return

        module_ids = dict(
            self.env.execute_query(
                SQL(
                    "SELECT name, id FROM ir_module_module WHERE name = ANY(%s)",
                    list({module for _table, module in missing}),
                )
            )
        )
        get_model_id = self.env["ir.model"]._get_id
        rows = []
        for (table, module), model_name in missing.items():
            module_id = module_ids.get(module)
            model_id = get_model_id(model_name)
            if module_id is None or model_id is None:
                _logger.warning(
                    "Cannot reflect m2m table %r of %r: unknown %s",
                    table,
                    model_name,
                    "module " + repr(module) if module_id is None else "model",
                )
                continue
            rows.append(
                SQL(
                    "(%s::varchar, %s::integer, %s::integer)",
                    table,
                    module_id,
                    model_id,
                )
            )
        if not rows:
            return

        self.env.execute_query(
            SQL(
                """INSERT INTO ir_model_relation
                       (name, module, model,
                        create_date, write_date, create_uid, write_uid)
                   SELECT v.name, v.module, v.model,
                          now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC',
                          %(uid)s, %(uid)s
                     FROM (VALUES %(values)s) AS v(name, module, model)""",
                values=SQL(", ").join(rows),
                uid=self.env.uid,
            )
        )
