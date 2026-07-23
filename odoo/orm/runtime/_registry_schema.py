"""Database schema and constraints: indexes, foreign keys, null checks.

Extracted from the Registry god-class; mixed into Registry (registry.py).
"""

import logging
import typing
import warnings
from collections.abc import Callable, Iterable

import psycopg

from odoo.tools import (
    sql,
)

from ..primitives import SUPERUSER_ID
from ._registry_stubs import _RegistryStubs

if typing.TYPE_CHECKING:
    from odoo.db import BaseCursor, Cursor
    from odoo.models import BaseModel


_logger = logging.getLogger("odoo.registry")
_schema = logging.getLogger("odoo.schema")


class _RegistrySchemaMixin(_RegistryStubs):
    """Database schema and constraints: indexes, foreign keys, null checks."""

    def post_constraint(
        self, cr: BaseCursor, func: Callable[[BaseCursor], None], key
    ) -> None:
        """Call the given function, and delay it if it fails during an upgrade."""
        try:
            if key not in self._constraint_queue:
                # skip if already queued: module A may fail to apply a constraint
                # and module B (inheriting A) reapply it successfully; running
                # the queued one again at end of cycle would fail on the
                # already-existing constraint.
                with cr.savepoint(flush=False):
                    func(cr)
            else:
                # already queued (module A failed to apply it): keep the latest
                # definition so finalize applies module B's version, not the
                # stale one from module A
                self._constraint_queue[key] = func
        except Exception as e:
            # "%s" % e, not *e.args: an empty-args exception would raise inside
            # this handler, and args[0] as a format string mangles messages that
            # contain a literal '%' (e.g. a constraint body with LIKE 'a%').
            if self._is_install:
                _schema.error("%s", e)
            else:
                _schema.info("%s", e)
                self._constraint_queue[key] = func

    def finalize_constraints(self, cr: Cursor) -> None:
        """Call the delayed functions from above."""
        for func in self._constraint_queue.values():
            try:
                with cr.savepoint(flush=False):
                    func(cr)
            except Exception as e:
                # warn only, this is not a deployment showstopper, and
                # can sometimes be a transient error
                _schema.warning("%s", e)
        self._constraint_queue.clear()

    def check_null_constraints(self, cr: Cursor) -> None:
        """Check that all not-null constraints are set."""
        cr.execute("""
            SELECT c.relname, a.attname
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = current_schema
            AND a.attnotnull = true
            AND a.attnum > 0
            AND a.attname != 'id';
        """)
        not_null_columns = set(cr.fetchall())

        self.not_null_fields.clear()
        for Model in self.models.values():
            if Model._auto and not Model._abstract:
                for field_name, field in Model._fields.items():
                    if field_name == "id":
                        self.not_null_fields.add(field)
                        continue
                    if field.column_type and field.store and field.required:
                        if (Model._table, field_name) in not_null_columns:
                            self.not_null_fields.add(field)
                        else:
                            _schema.warning("Missing not-null constraint on %s", field)

    def check_indexes(self, cr: Cursor, model_names: Iterable[str]) -> None:
        """Create or drop column indexes for the given models."""

        expected = [
            (sql.make_index_name(Model._table, field.name), Model._table, field)
            for model_name in model_names
            for Model in [self.models[model_name]]
            if Model._auto and not Model._abstract
            for field in Model._fields.values()
            if field.column_type and field.store
        ]
        if not expected:
            return

        # retrieve existing indexes with their table, access method and
        # predicate presence, scoped to the current schema (a same-named index
        # in another schema is not ours). The access method lets us detect an
        # index whose kind no longer matches the field (e.g. btree left behind
        # after index='trigram'); the predicate presence distinguishes a plain
        # btree from the partial `WHERE ... IS NOT NULL` one emitted for
        # index='btree_not_null' (both use the btree access method, so the
        # method alone cannot tell them apart).
        cr.execute(
            """
            SELECT idx.relname, tbl.relname, am.amname,
                   ix.indpred IS NOT NULL AS has_predicate
              FROM pg_index ix
              JOIN pg_class idx ON idx.oid = ix.indexrelid
              JOIN pg_class tbl ON tbl.oid = ix.indrelid
              JOIN pg_am am ON am.oid = idx.relam
             WHERE idx.relname = ANY(%s)
               AND idx.relnamespace = current_schema::regnamespace
            """,
            [[row[0] for row in expected]],
        )
        existing = {
            indexname: (tablename, method, has_predicate)
            for indexname, tablename, method, has_predicate in cr.fetchall()
        }

        for indexname, tablename, field in expected:
            index = field.index
            # raise (not assert): validates module-author `index=` input, so it
            # must hold under python -O too.
            if index not in ("btree", "btree_not_null", "trigram", True, False, None):
                raise ValueError(
                    f"Invalid index value {index!r} on {field}; allowed values: "
                    f"'btree', 'btree_not_null', 'trigram', True, False, None"
                )

            if index and field.translate and index != "trigram":
                _schema.warning(
                    f"Index attribute on {field!r} ignored, only trigram index is supported for translated fields"
                )
                continue

            # whether the field should be backed by an index, and the access
            # method (gin for trigram, btree otherwise) it is expected to use
            will_index = bool(index) and (
                (not field.translate and index != "trigram")
                or (index == "trigram" and self.has_trigram)
            )
            if indexname in existing:
                # the index already exists; rebuild it only when it no longer
                # matches the field: stale access method (the field changed its
                # index kind) or stale predicate presence (a 'btree' <->
                # 'btree_not_null' change keeps the btree method but adds or
                # drops the partial `WHERE ... IS NOT NULL` clause — including
                # the company_dependent variant)
                expected_method = "gin" if index == "trigram" else "btree"
                expected_predicate = index == "btree_not_null"
                _table, actual_method, actual_predicate = existing[indexname]
                stale = (
                    actual_method != expected_method
                    or bool(actual_predicate) != expected_predicate
                )
                will_index = will_index and stale
            else:
                stale = False

            if will_index:
                column_expression = f'"{field.name}"'
                if index == "trigram":
                    if field.translate:
                        column_expression = f"""(jsonb_path_query_array({column_expression}, '$.*')::text)"""
                    # add `unaccent` to the trigram index only because the
                    # trigram indexes are mainly used for (=)ilike search and
                    # unaccent is added only in these cases when searching
                    from odoo.modules.db import FunctionStatus

                    if self.has_unaccent == FunctionStatus.INDEXABLE:
                        column_expression = self.unaccent(column_expression)
                    elif self.has_unaccent:
                        warnings.warn(
                            "PostgreSQL function 'unaccent' is present but not immutable, "
                            "therefore trigram indexes may not be effective.",
                            stacklevel=1,
                        )
                    expression = f"{column_expression} gin_trgm_ops"
                    method = "gin"
                    where = ""
                elif index == "btree_not_null" and field.company_dependent:
                    # company dependent condition will use extra
                    # `AND col IS NOT NULL` to use the index.
                    expression = f"({column_expression} IS NOT NULL)"
                    method = "btree"
                    where = f"{column_expression} IS NOT NULL"
                else:  # index in ['btree', 'btree_not_null', True]
                    expression = f"{column_expression}"
                    method = "btree"
                    where = (
                        f"{column_expression} IS NOT NULL"
                        if index == "btree_not_null"
                        else ""
                    )
                try:
                    with cr.savepoint(flush=False):
                        # drop the stale index in the same savepoint as the
                        # recreation, so a failed rebuild rolls the drop back
                        # and never leaves the column unindexed
                        if stale:
                            sql.drop_index(cr, indexname, tablename)
                        sql.create_index(
                            cr,
                            indexname,
                            tablename,
                            [expression],
                            method,
                            where,
                        )
                except psycopg.OperationalError:
                    _schema.error("Unable to add index %r for %s", indexname, self)

            elif (
                not index
                and tablename == existing.get(indexname, (None, None, None))[0]
            ):
                _schema.info(
                    "Keep unexpected index %s on table %s", indexname, tablename
                )

    def add_foreign_key(
        self,
        table1: str,
        column1: str,
        table2: str,
        column2: str,
        ondelete: str,
        model: BaseModel,
        module: str,
        force: bool = True,
    ) -> None:
        """Specify an expected foreign key."""
        key = (table1, column1)
        val = (table2, column2, ondelete, model, module)
        if force:
            self._foreign_keys[key] = val
        else:
            self._foreign_keys.setdefault(key, val)

    def check_foreign_keys(self, cr: Cursor) -> None:
        """Create or update the expected foreign keys."""
        if not self._foreign_keys:
            return

        # determine existing foreign keys on the tables
        tablenames = {table for table, column in self._foreign_keys}
        existing = {
            (table1, column1): (name, table2, column2, deltype)
            for name, table1, column1, table2, column2, deltype in sql.get_fk_constraints_batch(
                cr, tablenames
            )
        }

        # create or update foreign keys
        for key, val in self._foreign_keys.items():
            table1, column1 = key
            table2, column2, ondelete, model, module = val
            deltype = sql._CONFDELTYPES[ondelete.upper()]
            spec = existing.get(key)
            if spec is None:
                sql.add_foreign_key(cr, table1, column1, table2, column2, ondelete)
                conname = sql.get_foreign_keys(
                    cr, table1, column1, table2, column2, ondelete
                )[0]
                model.env["ir.model.constraint"]._reflect_constraint(
                    model, conname, "f", None, module
                )
            elif (spec[1], spec[2], spec[3]) != (table2, column2, deltype):
                sql.drop_constraint(cr, table1, spec[0])
                sql.add_foreign_key(cr, table1, column1, table2, column2, ondelete)
                conname = sql.get_foreign_keys(
                    cr, table1, column1, table2, column2, ondelete
                )[0]
                model.env["ir.model.constraint"]._reflect_constraint(
                    model, conname, "f", None, module
                )

    def check_tables_exist(self, cr: Cursor) -> None:
        """
        Verify that all tables are present and try to initialize those that are missing.
        """
        from .environment import Environment

        env = Environment(cr, SUPERUSER_ID, {})
        table2model = {
            model._table: name
            for name, model in env.registry.items()
            if not model._abstract and not model._table_query
        }
        missing_tables = set(table2model).difference(
            sql.existing_tables(cr, table2model)
        )

        if missing_tables:
            missing = {table2model[table] for table in missing_tables}
            _logger.info("Models have no table: %s.", ", ".join(missing))
            # recreate missing tables
            for name in missing:
                _logger.info("Recreate table of model %s.", name)
                env[name].init()
            env.flush_all()
            # check again, and log errors if tables are still missing
            missing_tables = set(table2model).difference(
                sql.existing_tables(cr, table2model)
            )
            for table in missing_tables:
                _logger.error("Model %s has no table.", table2model[table])

    def is_an_ordinary_table(self, model: BaseModel) -> bool:
        """Return whether the given model has an ordinary table."""
        if self._ordinary_tables is None:
            cr = model.env.cr
            query = """
                SELECT c.relname
                  FROM pg_class c
                  JOIN pg_namespace n ON (n.oid = c.relnamespace)
                 WHERE c.relname = ANY(%s)
                   AND c.relkind = 'r'
                   AND n.nspname = current_schema
            """
            tables = [m._table for m in self.models.values()]
            cr.execute(query, [tables])
            self._ordinary_tables = {row[0] for row in cr.fetchall()}

        return model._table in self._ordinary_tables
