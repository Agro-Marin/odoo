import logging

from odoo import models
from odoo.libs.sql import SQL

_logger = logging.getLogger(__name__)


# ``mixin.materialized.view`` re-derives every row on every tick, because
# ``REFRESH MATERIALIZED VIEW`` has no partial form.  That is the right shape
# for a report over mutable source rows.  It is the wrong shape for a report
# whose grain is a closed period -- a day, a week -- where yesterday's answer
# is settled and only the newest period can still move.  Re-deriving the
# settled part is pure waste, and it grows without bound: the GPS daily report
# reached 69s and 2.7 GB of temp spill per hourly tick to produce the 95 rows
# that could change out of 7,404.
#
# So this stores the report in a real table and refreshes a trailing window:
# ``DELETE`` the rows at or after a cutoff, ``INSERT`` them back from the
# source.  Everything older is left alone.
#
# Two things make that give the same answer as a full rebuild rather than
# merely a similar one, and both are mandatory:
#
# - A bounded scan is not a bounded window.  If the report uses window
#   functions (``LAG``, running totals) then the first source row inside the
#   scan has no predecessor and computes differently than it would in a full
#   pass.  ``_rolling_scope`` must therefore also re-admit each partition's
#   last row from *before* the cutoff.  Measured on the GPS report, omitting
#   those seed rows silently dropped one capped time-gap per device that had
#   been quiet across the window edge: an answer that looks plausible and is
#   wrong.
# - The cutoff must land on a grain boundary.  Deleting from the middle of a
#   period and re-inserting only the part of it the scan saw would truncate
#   that period.  ``_rolling_cutoff_sql`` returns a value of the grain column,
#   not "now minus N days".
#
# A subclass declares the grain (``_rolling_key_field``), the window length
# (``_rolling_window_days``) and the scope predicate, and consults
# ``_rolling_scope_sql()`` wherever it builds its FROM.  ``refresh()`` then
# does the window; ``refresh(full=True)`` rebuilds from scratch, which is what
# to call when something feeding the settled part changes.
#
# Compose with ``mixin.sql.report``: the window refresh names the report's
# columns explicitly on both sides of its ``INSERT ... SELECT``, and takes
# them from ``_get_fields_select()``.
class MixinRollingReport(models.AbstractModel):
    """A report whose oldest rows never change, refreshed one window at a time."""

    _name = "mixin.rolling.report"
    _inherit = ["mixin.materialized.view"]
    _description = "Rolling-Window Report Mixin"

    _relation_kind = "r"

    #: Report column holding the closed-period grain.  Rows at or after the
    #: cutoff are rewritten; rows before it are never touched.
    _rolling_key_field = "date"

    #: How much of the tail to rewrite.  Must comfortably exceed both the
    #: refresh interval and the lateness of the source data -- devices that
    #: buffer while offline and replay later write rows into past periods.
    _rolling_window_days = 3

    # ------------------------------------------------------------------
    # WINDOW DEFINITION
    # ------------------------------------------------------------------

    def _rolling_cutoff_sql(self) -> SQL:
        """First grain value the window owns.

        Default ``current_date - _rolling_window_days``.  Override when the
        grain is bucketed in a specific timezone, which it usually is -- a
        report keyed on local day must cut on local midnight or it rewrites a
        partial period.
        """
        return SQL("(current_date - %s::int)", self._rolling_window_days)

    def _rolling_scope(self) -> SQL:
        """The SQL fragment that narrows the scan to the window.

        What it *is* is the subclass's choice, because only the subclass knows
        its own FROM: usually either a WHERE predicate or a replacement source
        relation.  Prefer the source relation when the source is large -- a
        predicate of the form ``timestamp >= cutoff OR id IN (seeds)`` cannot
        use an index and degrades into a sequential scan of the whole table,
        which on this fleet cost 9.9s against 1.9s for the equivalent
        per-partition range scan.

        Whichever form, it must cover the seed rows as well as the window.
        """
        raise NotImplementedError(
            f"{self._name}: override _rolling_scope() to narrow the scan to "
            "the window, seed rows included."
        )

    def _rolling_scope_sql(self) -> SQL:
        """The active scope fragment, or ``SQL.EMPTY`` outside a window refresh.

        Subclasses call this where they build their FROM, so one registry
        serves both the full rebuild and the window refresh.
        """
        return self.env.context.get("rolling_scope") or SQL.EMPTY

    def _rolling_query(self) -> SQL:
        """The report query restricted to the window, seed rows included."""
        return self.with_context(rolling_scope=self._rolling_scope())._query()

    # ------------------------------------------------------------------
    # REFRESH
    # ------------------------------------------------------------------

    def _mv_needs_rebuild(self, with_data=True) -> bool:
        """Whether the table on disk matches the current definition.

        Unlike the parent, an *empty* table is not a reason to rebuild. A
        materialized view that has never been refreshed cannot be read at all,
        so the parent treats emptiness as a defect; a table that is empty
        because the source is empty is simply correct, and rebuilding it on
        every upgrade to rediscover that is a full scan for nothing.
        """
        if self._relkind(self._table) != self._relation_kind:
            return True
        query_sql = self._query()
        return self._mv_stored_comment() != self._mv_definition_hash(
            query_sql, self._mv_index_cols()
        )

    def _is_populated(self, table) -> bool:
        """True when the backing table holds at least one row.

        The parent reads ``pg_class.relispopulated``, which means something for
        a materialized view and is always true for a table.
        """
        self.env.cr.execute(
            SQL("SELECT EXISTS (SELECT 1 FROM %s)", SQL.identifier(table))
        )
        return bool(self.env.cr.fetchone()[0])

    def refresh(self, full=False) -> bool:
        """Rewrite the trailing window, or every row when ``full``.

        :param full: rebuild from the source.  Required after anything that
            changes already-settled periods.
        :return: True on success, False when the table is missing.
        """
        if not self._view_exists(self._table):
            _logger.warning(
                "Rolling report table %s does not exist — skipping refresh. "
                "Run init() to create it.",
                self._table,
            )
            return False

        stale = self._rolling_pop_stale()
        if full or stale or not self._is_populated(self._table):
            if stale:
                _logger.info(
                    "%s was marked stale — rebuilding every period, not just "
                    "the window",
                    self._table,
                )
            self._create_materialized_view(index_field=self._mv_index_field)
            self.invalidate_model()
            return True

        table = SQL.identifier(self._table)
        key = SQL.identifier(self._rolling_key_field)
        cutoff = self._rolling_cutoff_sql()

        self.env.cr.execute(SQL("DELETE FROM %s WHERE %s >= %s", table, key, cutoff))
        deleted = self.env.cr.rowcount

        columns = SQL(", ").join(
            SQL.identifier(name) for name in self._get_fields_select()
        )
        self.env.cr.execute(
            SQL(
                "INSERT INTO %s (%s) SELECT %s FROM (%s) AS rolling WHERE %s >= %s",
                table,
                columns,
                columns,
                self._rolling_query(),
                key,
                cutoff,
            )
        )
        inserted = self.env.cr.rowcount

        # The rows were replaced under the ORM's feet. Their ids are stable by
        # construction (the grain's MIN(id)), so a cached record reads as
        # present and current while holding pre-refresh values -- a stale
        # report that looks like a fresh one.
        self.invalidate_model()

        _logger.info(
            "Rolling refresh of %s: %d row(s) replaced by %d over the last %d day(s)",
            self._table,
            deleted,
            inserted,
            self._rolling_window_days,
        )
        return True

    def _cron_refresh_materialized_view(self) -> bool:
        return self.refresh()

    # ------------------------------------------------------------------
    # STALENESS
    # ------------------------------------------------------------------

    def _rolling_stale_param(self) -> str:
        return f"{self._name}.rolling_full_rebuild"

    def _rolling_mark_stale(self) -> None:
        """Record that the settled part of the report no longer matches source.

        The window refresh never revisits closed periods, so anything that
        rewrites history -- a correction factor, an offset, a bulk import --
        has to say so.  Recorded as a flag rather than rebuilding inline
        because the caller is usually a user saving a form, and a rebuild is a
        full scan of the source.
        """
        self.env["ir.config_parameter"].sudo().set_param(
            self._rolling_stale_param(), "1"
        )
        _logger.info(
            "%s marked stale; the next refresh will rebuild in full", self._name
        )

    def _rolling_pop_stale(self) -> bool:
        """Consume the staleness flag, returning whether it was set."""
        parameters = self.env["ir.config_parameter"].sudo()
        if parameters.get_param(self._rolling_stale_param()) != "1":
            return False
        parameters.set_param(self._rolling_stale_param(), "0")
        return True

    # ------------------------------------------------------------------
    # CREATION
    # ------------------------------------------------------------------

    def _create_materialized_view(self, with_data=True, index_field="id"):
        """(Re)create the backing table, fully populated, plus its indexes.

        Keeps the parent's hook name so ``init()`` and ``_register_hook()`` are
        inherited unchanged.  ``with_data=False`` creates an empty table; the
        next ``refresh()`` finds it unpopulated and rebuilds.
        """
        table = SQL.identifier(self._table)
        query_sql = self._query()
        if not isinstance(query_sql, SQL) or not query_sql:
            raise TypeError(
                f"{self._name}._query() must return a non-empty SQL object, "
                f"got {type(query_sql).__name__}: {query_sql!r}",
            )

        self._drop_existing_relation(table)

        if with_data:
            _logger.info("Creating rolling report table %s WITH DATA", self._table)
            self.env.cr.execute(SQL("CREATE TABLE %s AS %s", table, query_sql))
        else:
            _logger.info("Creating rolling report table %s WITH NO DATA", self._table)
            self.env.cr.execute(
                SQL("CREATE TABLE %s AS %s WITH NO DATA", table, query_sql)
            )

        index_cols = self._mv_index_cols(index_field)
        if not index_cols:
            raise ValueError(
                f"{self._name}: index_field must name at least one column "
                "for the unique index the ORM reads this report by."
            )
        self.env.cr.execute(
            SQL(
                "CREATE UNIQUE INDEX IF NOT EXISTS %s ON %s (%s)",
                SQL.identifier(f"id_{self._table}"),
                table,
                SQL(", ").join(SQL.identifier(col) for col in index_cols),
            )
        )
        # The window refresh deletes and re-inserts by the grain column on
        # every tick, which is a sequential scan of the whole report without an
        # index on it.
        self.env.cr.execute(
            SQL(
                "CREATE INDEX IF NOT EXISTS %s ON %s (%s)",
                SQL.identifier(f"{self._table}__{self._rolling_key_field}_idx"),
                table,
                SQL.identifier(self._rolling_key_field),
            )
        )
        self.env.cr.execute(
            SQL(
                "COMMENT ON TABLE %s IS %s",
                table,
                self._mv_definition_hash(query_sql, index_cols),
            )
        )
