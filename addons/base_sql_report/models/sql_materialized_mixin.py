import logging

import psycopg

from odoo import models
from odoo.exceptions import UserError
from odoo.tools.sql import SQL

_logger = logging.getLogger(__name__)


# Transient Postgres errors that are safe to surface as "retry on next cron".
# Anything else (programming errors, auth, corruption) must propagate so the
# cron's error log actually records it.
_TRANSIENT_REFRESH_ERRORS = (
    psycopg.errors.SerializationFailure,
    psycopg.errors.LockNotAvailable,
    psycopg.errors.DeadlockDetected,
)


class MaterializedViewMixin(models.AbstractModel):
    """Abstract mixin for models backed by PostgreSQL materialized views.

    Provides idempotent ``_create_materialized_view()``, safe ``refresh()`` with
    a fallback between CONCURRENTLY and blocking variants, and a cron entry
    point.  Introspection queries are scoped to ``current_schema`` so multi-
    schema databases are handled correctly.

    Combining with ``sql.report.mixin``
    -----------------------------------
    The two mixins are designed to compose:

        _inherit = ["sql.report.mixin", "materialized.view.mixin"]

    The ``_materialized = True`` marker set by this mixin makes
    ``sql.report.mixin._table_query`` return ``None``, so the ORM reads the
    physical materialized view at ``self._table`` (fast) instead of inlining
    the analytical query as a subquery (slow).  ``_create_materialized_view``
    still uses the registry-built SQL via ``_query()`` to populate the MV.

    Stand-alone usage
    -----------------
    When inherited without ``sql.report.mixin``, the subclass must override
    ``_query()`` to return the defining SQL.
    """

    _name = "materialized.view.mixin"
    _description = "Materialized View Mixin"

    # Consumed by sql.report.mixin._table_query: True makes the ORM read
    # from the physical relation rather than re-inlining the analytical query.
    _materialized = True

    # ------------------------------------------------------------------
    # QUERY ACCESSOR
    # ------------------------------------------------------------------

    def _query(self):
        """Return the defining ``SQL`` for the materialized view.

        Resolution order (so ``_inherit`` order between the two mixins doesn't
        matter):

        1. ``_build_table_query`` if present — from ``sql.report.mixin``.
        2. ``_table_query`` attribute if it's a non-empty ``SQL`` or ``str``.
        3. Otherwise raise ``NotImplementedError``.

        Stand-alone usage (no ``sql.report.mixin``) requires overriding this
        method.
        """
        build = getattr(self, "_build_table_query", None)
        if callable(build):
            sql_obj = build()
            if isinstance(sql_obj, SQL) and sql_obj:
                return sql_obj
        table_query = getattr(self, "_table_query", None)
        if isinstance(table_query, SQL) and table_query:
            return table_query
        if isinstance(table_query, str) and table_query:
            return SQL(table_query)
        raise NotImplementedError(
            f"{self._name}: override _query() to return a non-empty SQL object, "
            "or inherit 'sql.report.mixin' for the registry pattern."
        )

    # ------------------------------------------------------------------
    # POSTGRES INTROSPECTION (schema-scoped)
    # ------------------------------------------------------------------

    def _view_exists(self, table) -> bool:
        """True if a materialized view named ``table`` exists in the current schema."""
        self.env.cr.execute(
            SQL(
                "SELECT 1 FROM pg_class "
                "WHERE relname = %s "
                "AND relkind = 'm' "
                "AND relnamespace = current_schema::regnamespace",
                table,
            )
        )
        return bool(self.env.cr.fetchone())

    def _is_populated(self, table) -> bool:
        """True if the materialized view ``table`` has been populated with data."""
        self.env.cr.execute(
            SQL(
                "SELECT relispopulated FROM pg_class "
                "WHERE relname = %s "
                "AND relkind = 'm' "
                "AND relnamespace = current_schema::regnamespace",
                table,
            )
        )
        row = self.env.cr.fetchone()
        return bool(row and row[0])

    def _relkind(self, table):
        """Return ``pg_class.relkind`` for ``table`` in the current schema, or None."""
        self.env.cr.execute(
            SQL(
                "SELECT relkind FROM pg_class "
                "WHERE relname = %s "
                "AND relnamespace = current_schema::regnamespace",
                table,
            )
        )
        row = self.env.cr.fetchone()
        return row[0] if row else None

    def _dependent_relations(self, table) -> list:
        """List views / matviews that depend on ``table`` (would be dropped by CASCADE)."""
        self.env.cr.execute(
            SQL(
                """
            SELECT DISTINCT c2.relname, c2.relkind
            FROM pg_depend d
            JOIN pg_class c1 ON d.refobjid = c1.oid
            JOIN pg_rewrite r ON d.objid = r.oid
            JOIN pg_class c2 ON r.ev_class = c2.oid
            WHERE c1.relname = %s
              AND c1.relnamespace = current_schema::regnamespace
              AND c2.relname != c1.relname
            """,
                table,
            )
        )
        return list(self.env.cr.fetchall())

    # ------------------------------------------------------------------
    # REFRESH
    # ------------------------------------------------------------------

    def refresh(self) -> bool:
        """Refresh the materialized view.

        Falls back to a blocking (non-concurrent) refresh on the first call
        because PostgreSQL rejects CONCURRENTLY on unpopulated MVs with
        ``FeatureNotSupported``.

        Returns True on success, False if the view doesn't exist or a
        transient error occurred.  Non-transient errors propagate so the
        cron's error log actually shows them.
        """
        if not self._view_exists(self._table):
            _logger.warning(
                "Materialized view %s does not exist — skipping refresh. "
                "Run init() to create it.",
                self._table,
            )
            return False

        table_name = SQL.identifier(self._table)
        try:
            if self._is_populated(self._table):
                _logger.info("Refreshing %s (CONCURRENTLY)", self._table)
                self.env.cr.execute(
                    SQL("REFRESH MATERIALIZED VIEW CONCURRENTLY %s", table_name),
                )
            else:
                _logger.info("Refreshing %s (blocking, first refresh)", self._table)
                self.env.cr.execute(
                    SQL("REFRESH MATERIALIZED VIEW %s", table_name),
                )
        except _TRANSIENT_REFRESH_ERRORS as exc:
            _logger.warning(
                "Transient refresh failure on %s: %s. Cron will retry.",
                self._table,
                exc,
            )
            return False
        return True

    def _cron_refresh_materialized_view(self) -> bool:
        """Cron entry point.  Thin wrapper around ``refresh()``."""
        return self.refresh()

    # ------------------------------------------------------------------
    # CREATION
    # ------------------------------------------------------------------

    def _create_materialized_view(self, with_data=True, index_field="id"):
        """(Re)create the materialized view and its unique index.

        Args:
            with_data: If True (default), populate immediately (``WITH DATA``).
                Default changed from False — PostgreSQL rejects SELECT on
                unpopulated MVs with ``ObjectNotInPrerequisiteState``, which
                would make reports fail hard between install and first cron
                refresh.  Pass ``with_data=False`` only for MVs so large that
                install latency outweighs availability, and queue a refresh
                immediately after module install.
            index_field: Column for the UNIQUE index required by REFRESH
                MATERIALIZED VIEW CONCURRENTLY.  Defaults to ``"id"``.

        Raises:
            UserError: if ``self._table`` is already used by a regular table
                or any relation kind other than view / materialized view.
        """
        table_name = SQL.identifier(self._table)
        query_sql = self._query()
        if not isinstance(query_sql, SQL) or not query_sql:
            raise TypeError(
                f"{self._name}._query() must return a non-empty SQL object, "
                f"got {type(query_sql).__name__}: {query_sql!r}",
            )

        self._drop_existing_relation(table_name)

        if with_data:
            _logger.info("Creating materialized view %s WITH DATA", self._table)
            self.env.cr.execute(
                SQL("CREATE MATERIALIZED VIEW %s AS %s", table_name, query_sql),
            )
        else:
            _logger.warning(
                "Creating %s WITH NO DATA — SELECT on this MV will raise "
                "ObjectNotInPrerequisiteState until the first refresh().",
                self._table,
            )
            self.env.cr.execute(
                SQL(
                    "CREATE MATERIALIZED VIEW %s AS %s WITH NO DATA",
                    table_name,
                    query_sql,
                ),
            )

        index_name = SQL.identifier(f"id_{self._table}")
        index_field_sql = SQL.identifier(index_field)
        _logger.info(
            "Creating unique index id_%s on %s(%s)",
            self._table,
            self._table,
            index_field,
        )
        self.env.cr.execute(
            SQL(
                "CREATE UNIQUE INDEX IF NOT EXISTS %s ON %s (%s)",
                index_name,
                table_name,
                index_field_sql,
            ),
        )

    def _drop_existing_relation(self, table_name_sql):
        """Drop an existing view / materialized view safely.

        Warns loudly when dependent objects would be CASCADE-dropped; refuses
        to proceed when the name is used by a regular table (data-loss risk).
        """
        kind = self._relkind(self._table)
        if kind is None:
            return
        if kind in ("r", "p"):
            raise UserError(
                f"Cannot create materialized view {self._table!r}: a regular "
                f"table with that name already exists (relkind={kind!r}). "
                "Drop or rename it manually before upgrading the module."
            )
        if kind not in ("v", "m"):
            raise UserError(
                f"Cannot (re)create materialized view {self._table!r}: "
                f"unexpected pg_class relkind {kind!r}.  Investigate manually."
            )

        dependents = self._dependent_relations(self._table)
        if dependents:
            _logger.warning(
                "Dropping %s %s will CASCADE %d dependent relation(s): %s",
                "materialized view" if kind == "m" else "view",
                self._table,
                len(dependents),
                [f"{name} (kind={relkind})" for name, relkind in dependents],
            )

        if kind == "v":
            _logger.info(
                "Dropping regular view %s (migration to materialized)", self._table
            )
            self.env.cr.execute(SQL("DROP VIEW IF EXISTS %s CASCADE", table_name_sql))
        else:
            _logger.info("Dropping materialized view %s", self._table)
            self.env.cr.execute(
                SQL("DROP MATERIALIZED VIEW IF EXISTS %s CASCADE", table_name_sql),
            )
