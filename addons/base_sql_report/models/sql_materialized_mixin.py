import hashlib
import logging

import psycopg

from odoo import _, models
from odoo.exceptions import UserError
from odoo.tools.sql import SQL

_logger = logging.getLogger(__name__)

# Marker prefix for the definition hash stored as the COMMENT of every
# materialized view managed by this mixin (see _mv_definition_hash).
_MV_COMMENT_PREFIX = "odoo-mv:v1:"


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

    # Column (or list of columns) for the UNIQUE index that REFRESH ...
    # CONCURRENTLY requires.  Consumed by the default ``init()`` below; a
    # concrete model may override this attribute instead of writing its own
    # ``init()``.
    _mv_index_field = "id"

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

        The REFRESH runs inside a SAVEPOINT.  A failed statement aborts the
        whole PostgreSQL transaction, so without the savepoint a swallowed
        transient error would leave the cursor in ``InFailedSqlTransaction``
        state — every later statement (e.g. the next MV in a loop-over-many
        cron) would then fail even though this method returned ``False``.
        ``ROLLBACK TO SAVEPOINT`` localises the failure to this one refresh.

        Pending ORM writes are not flushed before the refresh (``flush=False``):
        the MV is defined over committed data, and callers that need in-flight
        writes reflected must flush explicitly beforehand.
        """
        if not self._view_exists(self._table):
            _logger.warning(
                "Materialized view %s does not exist — skipping refresh. "
                "Run init() to create it.",
                self._table,
            )
            return False

        table_name = SQL.identifier(self._table)
        concurrently = self._is_populated(self._table)
        try:
            with self.env.cr.savepoint(flush=False):
                if concurrently:
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

    def init(self):
        """Default schema hook: (re)create the MV on install / upgrade.

        Reads ``with_data`` from context (default True — the safe choice; see
        ``_create_materialized_view``) and uses ``_mv_index_field`` for the
        unique index.  A concrete model only needs to set ``_mv_index_field``;
        override this method directly only for non-default ``with_data`` logic.

        No-op for abstract models: ``registry.init_models`` calls ``init()`` on
        every model, including this mixin itself, which has no table.

        Rebuild policy — ``init()`` runs once per upgraded module whose model
        closure contains this model, which on a ``-u base`` means many times
        per load, each a full ``CREATE ... WITH DATA`` over the source tables
        (measured minutes on a production database).  So:

        * view missing: create immediately (data loading and ``at_install``
          tests may SELECT it before the end-of-load hook runs);
        * registry still loading: defer to ``_register_hook`` (end of load),
          where the *final* model definition builds the query exactly once;
        * otherwise (e.g. ``reload_schema`` on a running server): rebuild only
          if the stored definition hash differs (see ``_mv_needs_rebuild``).
        """
        if self._abstract:
            return
        with_data = self.env.context.get("with_data", True)
        if not self._view_exists(self._table):
            self._create_materialized_view(
                with_data=with_data, index_field=self._mv_index_field
            )
            return
        if not self.pool.loaded:
            pending = getattr(self.pool, "_pending_materialized_views", None)
            if pending is None:
                pending = self.pool._pending_materialized_views = {}
            pending[self._name] = with_data
            return
        if self._mv_needs_rebuild(with_data=with_data):
            self._create_materialized_view(
                with_data=with_data, index_field=self._mv_index_field
            )

    def _register_hook(self) -> None:
        """Process a rebuild deferred by ``init()`` during module loading.

        Called once per registry load after all modules are in (and again on
        incremental setups of a ready registry, where the pending map is
        normally empty).  Cheap no-op when this model has nothing pending.
        """
        super()._register_hook()
        if self._abstract:
            return
        pending = getattr(self.pool, "_pending_materialized_views", None)
        if pending is None or self._name not in pending:
            return
        with_data = pending.pop(self._name)
        if self._mv_needs_rebuild(with_data=with_data):
            self._create_materialized_view(
                with_data=with_data, index_field=self._mv_index_field
            )

    def _mv_index_cols(self, index_field=None) -> list:
        """Normalize ``_mv_index_field`` (or an explicit value) to a list."""
        index_field = index_field if index_field is not None else self._mv_index_field
        return [index_field] if isinstance(index_field, str) else list(index_field)

    def _mv_definition_hash(self, query_sql: SQL, index_cols: list) -> str:
        """Return the marker comment identifying this MV definition.

        Hashes the defining SQL (code and parameters) and the unique-index
        columns; stored as ``COMMENT ON MATERIALIZED VIEW`` by
        ``_create_materialized_view`` and compared by ``_mv_needs_rebuild``.
        """
        payload = "\x00".join(
            (query_sql.code, repr(query_sql.params), ",".join(index_cols))
        )
        digest = hashlib.sha256(payload.encode()).hexdigest()
        return f"{_MV_COMMENT_PREFIX}{digest}"

    def _mv_stored_comment(self):
        """Return the comment stored on the MV, or None."""
        self.env.cr.execute(
            SQL(
                "SELECT obj_description(c.oid, 'pg_class') FROM pg_class c "
                "WHERE c.relname = %s AND c.relkind = 'm' "
                "AND c.relnamespace = current_schema::regnamespace",
                self._table,
            )
        )
        row = self.env.cr.fetchone()
        return row[0] if row else None

    def _mv_needs_rebuild(self, with_data=True) -> bool:
        """Whether the existing relation matches the current definition.

        True when the stored definition hash differs (including legacy MVs
        created before hashes were stamped, and plain views pending migration),
        or when the MV is unpopulated while ``with_data`` is requested.
        """
        if self._relkind(self._table) != "m":
            return True
        query_sql = self._query()
        index_cols = self._mv_index_cols()
        if self._mv_stored_comment() != self._mv_definition_hash(query_sql, index_cols):
            return True
        return bool(with_data) and not self._is_populated(self._table)

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
            index_field: Column (``str``) or columns (list/tuple of ``str``)
                for the UNIQUE index required by REFRESH MATERIALIZED VIEW
                CONCURRENTLY.  Defaults to ``"id"``.  A composite key must be
                unique across the MV rows.

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

        index_cols = self._mv_index_cols(index_field)
        if not index_cols:
            raise ValueError(
                f"{self._name}: index_field must name at least one column "
                "for the unique index REFRESH ... CONCURRENTLY requires."
            )
        index_name = SQL.identifier(f"id_{self._table}")
        index_cols_sql = SQL(", ").join(SQL.identifier(col) for col in index_cols)
        _logger.info(
            "Creating unique index id_%s on %s(%s)",
            self._table,
            self._table,
            ", ".join(index_cols),
        )
        self.env.cr.execute(
            SQL(
                "CREATE UNIQUE INDEX IF NOT EXISTS %s ON %s (%s)",
                index_name,
                table_name,
                index_cols_sql,
            ),
        )

        # Stamp the definition hash so later init() calls can recognize an
        # up-to-date MV and skip the rebuild (see _mv_needs_rebuild).
        self.env.cr.execute(
            SQL(
                "COMMENT ON MATERIALIZED VIEW %s IS %s",
                table_name,
                self._mv_definition_hash(query_sql, index_cols),
            )
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
                _(
                    "Cannot create materialized view %(table)r: a regular "
                    "table with that name already exists (relkind=%(kind)r). "
                    "Drop or rename it manually before upgrading the module.",
                    table=self._table,
                    kind=kind,
                )
            )
        if kind not in ("v", "m"):
            raise UserError(
                _(
                    "Cannot (re)create materialized view %(table)r: "
                    "unexpected pg_class relkind %(kind)r.  Investigate manually.",
                    table=self._table,
                    kind=kind,
                )
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
