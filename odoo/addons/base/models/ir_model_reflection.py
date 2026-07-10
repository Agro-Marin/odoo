"""Schema-reflection bookkeeping models.

These models record the PostgreSQL schema objects (constraints, indexes and
many2many relation tables) that Odoo models create, so they can be dropped again
when the owning module is uninstalled. Split out of ``ir_model_access.py``, with
which they share no logic.
"""

import logging
from typing import Any, Self

from psycopg.types.json import Json, Jsonb

from odoo import fields, models
from odoo.api import ValuesType
from odoo.exceptions import AccessError
from odoo.tools import SQL, OrderedSet, sql
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

        # Fetch, in a single query, every constraint record that shares a name
        # with the records being deleted. A schema object is only dropped when
        # *all* of its owners are in this unlink set: an installed module may
        # define the same-named element and would then still need it.
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
                # installed modules still own this schema element: keep it
                continue

            hname = sql.make_identifier(name)
            typ = data.type
            if typ in ("f", "u"):
                table = (
                    self.env[data.model.model]._table
                    if data.model.model in self.env
                    else data.model.model.replace(".", "_")
                )
                # Our type='u' means any "other" constraint, so match check/
                # unique/exclude ('c','u','x') and exclude primary and foreign
                # keys. An 'f' may live on a related m2m table, which we ignore.
                # See: https://www.postgresql.org/docs/9.5/catalog-pg-constraint.html
                if self.env.execute_query(
                    SQL(
                        """SELECT
                    FROM pg_constraint cs
                    JOIN pg_class cl
                    ON (cs.conrelid = cl.oid)
                    WHERE cs.contype = ANY(%s) AND cs.conname = %s AND cl.relname = %s
                    AND cl.relnamespace = current_schema::regnamespace
                    """,
                        ["c", "u", "x"] if typ == "u" else [typ],
                        hname,
                        table,
                    )
                ):
                    self.env.execute_query(
                        SQL(
                            "ALTER TABLE %s DROP CONSTRAINT %s",
                            SQL.identifier(table),
                            SQL.identifier(hname),
                        )
                    )
                    _logger.info("Dropped CONSTRAINT %s@%s", name, data.model.model)

            elif typ == "i":
                # drop index if it exists
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
            # no need to save constraints for custom models as they're not part
            # of any module
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
        # expected rows, keyed by (name, module_name)
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

        # one SELECT for all (name, module) pairs
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

        # one upsert for the created/changed rows
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

        # batched xml-id update; unchanged rows only get marked as loaded
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

        # Fetch, in a single query, every relation record sharing a name with
        # the records being deleted, so the ownership check below is O(1) per
        # record instead of one round-trip each.
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
            # only drop the table when every record owning it is being deleted;
            # installed modules may still need it
            if not owners.get(name, set()).issubset(ids_set):
                continue
            if sql.table_exists(self.env.cr, name):
                to_drop.add(name)

        self.unlink()

        # drop m2m relation tables
        for table in to_drop:
            self.env.cr.execute(SQL("DROP TABLE %s CASCADE", SQL.identifier(table)))
            _logger.info("Dropped table %s", table)

    def _reflect_relation(self, model: Any, table: str, module: str) -> None:
        """Reflect the m2m table of the given model so it can be dropped when
        the module is uninstalled."""
        # No cache invalidation needed: this reads and writes ir_model_relation
        # through raw SQL only (like the sibling ``_reflect_constraint``), so
        # the ORM record cache is never consulted here.
        if not self.env.execute_query(
            SQL(
                """SELECT 1 FROM ir_model_relation r, ir_module_module m
                   WHERE r.module = m.id AND r.name = %s AND m.name = %s""",
                table,
                module,
            )
        ):
            self.env.execute_query(
                SQL(
                    """INSERT INTO ir_model_relation
                           (name, create_date, write_date, create_uid, write_uid, module, model)
                       VALUES (%s,
                               now() AT TIME ZONE 'UTC',
                               now() AT TIME ZONE 'UTC',
                               %s, %s,
                               (SELECT id FROM ir_module_module WHERE name = %s),
                               (SELECT id FROM ir_model WHERE model = %s))""",
                    table,
                    self.env.uid,
                    self.env.uid,
                    module,
                    model._name,
                )
            )
