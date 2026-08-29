from itertools import starmap

from odoo import models
from odoo.libs.sql import SQL


# This mixin builds the query of ``_auto = False`` reports from structured
# registries (dicts for SELECT, lists for FROM / WHERE / GROUP / HAVING /
# ORDER) rather than from string-manipulation of monolithic SQL methods.
# Subclasses add, modify, or remove entries via normal dict / list operations.
#
# One name for the query
# ----------------------
# ``_query()`` assembles and returns it.  ``mixin.materialized.view`` calls the
# same method to obtain the SQL that DEFINES its relation, so a report has one
# spelling for "my SQL" whichever mixins it composes.  ``_table_query`` is the
# ORM's own hook and means something narrower -- see the property below.
#
# Composition with ``mixin.materialized.view``
# ---------------------------------------------
# When a model also inherits ``mixin.materialized.view``, its ``_materialized``
# class attribute is True.  ``_table_query`` then returns ``None`` so the ORM
# reads from the physical relation at ``self._table`` instead of inlining the
# query as a subquery.  ``_query()`` is still what populates that relation.
#
# Trust contract for registry values
# -----------------------------------
# Every string returned by the ``_get_*`` methods is inserted into SQL
# verbatim -- there is no parameter binding. *Never* build registry values
# from ``self.env.context``, request data, or any other untrusted source.
# For parameterized conditions, return a ``SQL`` object directly (supported
# in ``_get_where_conditions`` and ``_get_having_conditions``) -- e.g.
# ``SQL("o.partner_id = %s", partner_id)``.
#
# ⚠ On a MATERIALIZED model a bound parameter is frozen, not live.
# ``CREATE MATERIALIZED VIEW`` inlines it as a literal, and ``REFRESH`` re-runs
# that stored definition forever -- so ``SQL("l.date <= %s", fields.Date.today())``
# pins the report to the day the relation was built.  ``refresh()`` detects the
# drift and rebuilds (see ``mixin.materialized.view._relation_needs_rebuild``),
# but a value that moves on every tick then rebuilds on every tick.  Prefer SQL
# that PostgreSQL evaluates itself (``current_date``) for anything time-varying.
#
# Registry hooks (override these)
# ---------------------------------
# - ``_get_fields_select() -> dict``     : ``{field_name: sql_expression}``
# - ``_get_from_tables()  -> list``      : ``[(table, alias, join_type, on)]``
# - ``_get_where_conditions() -> list``  : ``[str | SQL]``
# - ``_get_fields_group_by()  -> list``  : ``[str]``
# - ``_get_having_conditions() -> list`` : ``[str | SQL]``
# - ``_get_fields_order_by()  -> list``  : ``[str]``
# - ``_with_cte() -> SQL`` (optional, default ``SQL.EMPTY``)
#
# Example
# -------
# class MyReport(models.Model):
#     _name = "my.report"
#     _inherit = "mixin.sql.report"
#     _auto = False
#
#     product_id = fields.Many2one("product.product", readonly=True)
#     total_qty = fields.Float(readonly=True)
#
#     def _get_fields_select(self):
#         return {
#             "id": "MIN(l.id)",
#             "product_id": "l.product_id",
#             "total_qty": "SUM(l.quantity)",
#         }
#
#     def _get_from_tables(self):
#         return [
#             ("sale_order_line", "l", None, None),
#             ("sale_order", "o", "LEFT JOIN", "l.order_id = o.id"),
#         ]
#
#     def _get_where_conditions(self):
#         return ["l.display_type IS NULL"]
#
#     def _get_fields_group_by(self):
#         return ["l.product_id"]
class MixinSqlReport(models.AbstractModel):
    """Registry-driven SQL construction for ``_auto = False`` analytical reports."""

    _name = "mixin.sql.report"
    _description = "SQL Report Construction Helper"
    _auto = False

    # ------------------------------------------------------------------
    # PUBLIC QUERY ACCESSORS
    # ------------------------------------------------------------------

    def _query(self) -> SQL:
        """Assemble the analytical query from all registries.

        The single source of this report's SQL: read by ``_table_query`` for
        the ORM, and by ``mixin.materialized.view`` to define its relation.

        Always returns a non-empty ``SQL`` object.  Raises
        ``NotImplementedError`` if ``_get_fields_select`` or ``_get_from_tables``
        are empty — those two registries are mandatory.

        Do not override this method.  Override the registry hooks instead.
        """
        cte = self._with_cte()
        clauses = (
            self._build_where(),
            self._build_group_by(),
            self._build_having(),
            self._build_order_by(),
        )

        parts = []
        if cte:
            parts.append(SQL("WITH %s", cte))
        parts.extend([self._build_select(), self._build_from()])
        parts.extend(clause for clause in clauses if clause)
        return SQL("\n").join(parts)

    @property
    def _table_query(self):
        """ORM table source — subquery SQL, or None when the model is materialized.

        Consulted by ``BaseModel._table_sql`` (core ORM).  Returning ``None``
        makes the ORM read ``FROM "self._table"`` (the physical relation).
        Returning SQL makes the ORM inline ``FROM (SQL) AS "self._table"``.

        ``getattr`` (not ``self._materialized``) so neither this mixin nor the
        MRO order owns the default — the marker exists only when the MV mixin
        explicitly sets it, regardless of ``_inherit`` order.
        """
        if getattr(self, "_materialized", False):
            return None
        return self._query()

    # ------------------------------------------------------------------
    # BUILDER METHODS (do not override)
    # ------------------------------------------------------------------
    # Spelled ``_build_*`` and not ``_select`` / ``_from`` / ``_where`` /
    # ``_group_by`` / ``_order_by``, which is what they were. Those five names
    # are already taken across this workspace by the pattern this mixin exists
    # to replace: 13 report models assemble a CREATE VIEW from methods of
    # exactly those names, 39 more override them, and ~97 call sites read them
    # back -- returning **str** in most, **SQL** in eight. A model inheriting
    # this mixin and one of those bases would have silently overridden a clause
    # builder with a string producer. No file does both today; renaming here
    # means none ever can, and it is what makes migrating those 13 mechanical
    # rather than a per-file audit.

    def _with_cte(self) -> SQL:
        """Common Table Expression (body only, no WITH keyword).

        Default empty.  Override to return ``SQL("cte_name AS (...), ...")``.
        """
        return SQL.EMPTY

    def _build_select(self) -> SQL:
        """Build the ``SELECT`` clause from the field registry."""
        fields = self._get_fields_select()
        if not fields:
            raise NotImplementedError(
                f"{self._name}: override _get_fields_select() to return a "
                "non-empty {field_name: sql_expression} mapping."
            )
        field_parts = []
        for field_name, expression in fields.items():
            self._check_percent_escaping(expression, f"select[{field_name!r}]")
            field_parts.append(
                SQL("%s AS %s", SQL(expression), SQL.identifier(field_name)),
            )
        return SQL("SELECT\n    %s", SQL(",\n    ").join(field_parts))

    def _build_from(self) -> SQL:
        """Build the ``FROM`` clause from the table registry."""
        tables = self._get_from_tables()
        if not tables:
            raise NotImplementedError(
                f"{self._name}: override _get_from_tables() to return a "
                "non-empty list of (table, alias, join_type, on_condition) tuples."
            )
        from_parts = list(starmap(self._prepare_from_entry, tables))
        return SQL("FROM\n    %s", SQL("\n    ").join(from_parts))

    def _prepare_from_entry(self, table_name, alias, join_type, on_condition) -> SQL:
        """Render a single ``(table, alias, join_type, on)`` entry.

        Base table (``join_type is None``) → ``<table> [<alias>]``.
        JOIN entry → ``<join_type> <table> [<alias>] [ON <condition>]``.

        **A ``SQL`` ``table_name`` binds its own name, so ``alias`` is not
        rendered for one.**  It is still worth passing: it documents the name
        the rest of the registry writes its ON condition and SELECT expressions
        against.

        That is not a nicety.  ``res.currency._get_simple_currency_table``
        returns *either* ``SQL("(VALUES ...) AS account_currency_table(...)")``
        or a bare ``SQL("account_currency_table")`` depending on how many
        currencies the companies use, and ``sale.report`` / ``purchase.report``
        pass ``alias="account_currency_table"`` for both.  Rendering the alias
        would produce ``(VALUES ...) AS account_currency_table(...)
        account_currency_table``, which PostgreSQL rejects; the old code got
        the JOIN case right by dropping it and the *base* case wrong by not.
        Dropping it on both is what makes the two consistent.
        """
        if isinstance(table_name, SQL):
            table_sql = table_name
        else:
            self._check_percent_escaping(table_name, "from-table")
            table_sql = SQL(table_name)
            if alias:
                self._check_percent_escaping(alias, "from-alias")
                table_sql = SQL("%s %s", table_sql, SQL(alias))
        if join_type is None:
            return table_sql
        if not on_condition:
            return SQL("%s %s", SQL(join_type), table_sql)
        self._check_percent_escaping(on_condition, f"from-join[{alias!r}]")
        return SQL("%s %s ON %s", SQL(join_type), table_sql, SQL(on_condition))

    def _build_where(self) -> SQL:
        """Build the ``WHERE`` clause from the condition registry."""
        return self._build_conditions(
            SQL("WHERE"), self._get_where_conditions(), "where"
        )

    def _build_having(self) -> SQL:
        """Build the ``HAVING`` clause from the condition registry.

        Aggregate filters belong here, not appended to a ``_get_fields_group_by``
        entry — that smuggle assembles and runs, which is exactly why it needs a
        named home.
        """
        return self._build_conditions(
            SQL("HAVING"), self._get_having_conditions(), "having"
        )

    def _build_conditions(self, keyword_sql, conditions, location) -> SQL:
        """Join ``conditions`` with AND under ``keyword``, or ``SQL.EMPTY``.

        Accepts both strings (wrapped in ``SQL(...)``) and ``SQL`` objects
        (inserted as-is).  Use ``SQL`` objects for parameterized conditions.
        """
        if not conditions:
            return SQL.EMPTY
        condition_parts = []
        for cond in conditions:
            if isinstance(cond, SQL):
                condition_parts.append(cond)
            else:
                self._check_percent_escaping(cond, location)
                condition_parts.append(SQL(cond))
        # keyword_sql arrives already wrapped: test_lint's SQL checker reads
        # the first argument of SQL() and a computed keyword reads as injection.
        return SQL(
            "%s\n    %s",
            keyword_sql,
            SQL("\n    AND ").join(condition_parts),
        )

    def _build_group_by(self) -> SQL:
        """Build the ``GROUP BY`` clause from the field registry."""
        return self._build_field_clause(
            SQL("GROUP BY"), self._get_fields_group_by(), "group_by"
        )

    def _build_order_by(self) -> SQL:
        """Build the ``ORDER BY`` clause from the field registry.

        Usually the ``_order`` class attribute is what you want — that
        controls Python-side record ordering.  Use this hook only when the
        defining query needs an explicit ``ORDER BY`` at creation time, which
        on a materialized model is a one-off clustering sort.
        """
        return self._build_field_clause(
            SQL("ORDER BY"), self._get_fields_order_by(), "order_by"
        )

    def _build_field_clause(self, keyword_sql, fields, location) -> SQL:
        """Join ``fields`` with commas under ``keyword``, or ``SQL.EMPTY``."""
        if not fields:
            return SQL.EMPTY
        field_parts = []
        for field in fields:
            self._check_percent_escaping(field, location)
            field_parts.append(SQL(field))
        return SQL(
            "%s\n    %s",
            keyword_sql,
            SQL(",\n    ").join(field_parts),
        )

    # ------------------------------------------------------------------
    # REGISTRY HOOKS (override in subclass)
    # ------------------------------------------------------------------

    def _get_fields_select(self) -> dict:
        """Return ``{field_name: sql_expression}`` for the SELECT clause.

        Mandatory override.  Dictionary insertion order is preserved in the
        generated SQL.  Expressions are raw SQL — see the class-level trust
        contract.
        """
        return {}

    def _get_from_tables(self) -> list:
        """Return the FROM-clause registry.

        Mandatory override.  Each entry is a 4-tuple
        ``(table_name, alias, join_type, on_condition)``.  The first entry is
        the base table (``join_type=None``); subsequent entries are JOINs.
        ``table_name`` may be a string or a ``SQL`` object embedding its own
        alias.
        """
        return []

    def _get_where_conditions(self) -> list:
        """Return row filters for the WHERE clause.

        Each element may be a string (inserted verbatim) or a ``SQL`` object
        (parameterized).  All conditions are joined with ``AND``.
        """
        return []

    def _get_fields_group_by(self) -> list:
        """Return non-aggregated field expressions for the GROUP BY clause."""
        return []

    def _get_having_conditions(self) -> list:
        """Return aggregate filters for the HAVING clause.

        Same element types as ``_get_where_conditions``.  Empty by default.
        """
        return []

    def _get_fields_order_by(self) -> list:
        """Return sort expressions for the ORDER BY clause (optional)."""
        return []

    # ------------------------------------------------------------------
    # REGISTRY VALIDATION
    # ------------------------------------------------------------------
    # Not a trust boundary — registry values are still inserted verbatim, as
    # the class-level contract says. This only turns one cryptic failure into a
    # message that names the offending slot.

    @staticmethod
    def _check_percent_escaping(expr, location):
        """Reject un-escaped ``%`` in registry strings.

        The ``SQL()`` constructor validates format-string shape via
        ``code % ()`` at build time.  A naive ``LIKE '%pattern%'`` therefore
        fails with a cryptic ``TypeError: not enough arguments for format
        string``.  Catch it here with a message that points at the offending
        registry slot.
        """
        if not isinstance(expr, str) or "%" not in expr:
            return
        if "%" in expr.replace("%%", ""):
            raise ValueError(
                f"mixin.sql.report: un-escaped '%' in {location}: {expr!r}. "
                "Use '%%' for literal percent (e.g. LIKE '%%x%%')."
            )
