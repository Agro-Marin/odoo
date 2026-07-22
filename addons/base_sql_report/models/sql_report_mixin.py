from odoo import models
from odoo.tools.sql import SQL


class SqlReportMixin(models.AbstractModel):
    """Registry-driven SQL construction for analytical reports.

    This mixin builds the ``FROM`` expression of ``_auto = False`` reports from
    structured registries (dicts for SELECT, lists for FROM / WHERE / GROUP /
    ORDER) rather than from string-manipulation of monolithic SQL methods.
    Subclasses add, modify, or remove entries via normal dict / list operations.

    Composition with ``materialized.view.mixin``
    --------------------------------------------
    When a model also inherits ``materialized.view.mixin``, its ``_materialized``
    class attribute is True.  ``_table_query`` then returns ``None`` so the ORM
    reads from the physical materialized view at ``self._table`` instead of
    inlining the query as a subquery.  ``_build_table_query()`` is still used to
    populate the MV via ``_create_materialized_view()``.

    Trust contract for registry values
    ----------------------------------
    Every string returned by the ``_get_*`` methods is inserted into SQL
    verbatim — there is no parameter binding.  **Never** build registry values
    from ``self.env.context``, request data, or any other untrusted source.
    For parameterized conditions, return a ``SQL`` object directly (supported
    in ``_get_where_conditions``) — e.g. ``SQL("o.partner_id = %s", partner_id)``.

    Registry hooks (override these)
    -------------------------------
    - ``_get_select_fields() -> dict``  : ``{field_name: sql_expression}``
    - ``_get_from_tables()  -> list``   : ``[(table, alias, join_type, on)]``
    - ``_get_where_conditions() -> list``  : ``[str | SQL]``
    - ``_get_group_by_fields()  -> list``  : ``[str]``
    - ``_get_order_by_fields()  -> list``  : ``[str]``
    - ``_with_cte() -> SQL`` (optional, default ``SQL.EMPTY``)

    Example
    -------
    ::

        class MyReport(models.Model):
            _name = "my.report"
            _inherit = "sql.report.mixin"
            _auto = False

            product_id = fields.Many2one("product.product", readonly=True)
            total_qty = fields.Float(readonly=True)

            def _get_select_fields(self):
                return {
                    "id": "MIN(l.id)",
                    "product_id": "l.product_id",
                    "total_qty": "SUM(l.quantity)",
                }

            def _get_from_tables(self):
                return [
                    ("sale_order_line", "l", None, None),
                    ("sale_order", "o", "LEFT JOIN", "l.order_id = o.id"),
                ]

            def _get_where_conditions(self):
                return ["l.display_type IS NULL"]

            def _get_group_by_fields(self):
                return ["l.product_id"]
    """

    _name = "sql.report.mixin"
    _description = "SQL Report Construction Helper"
    _auto = False

    # ------------------------------------------------------------------
    # PUBLIC QUERY ACCESSORS
    # ------------------------------------------------------------------

    def _build_table_query(self) -> SQL:
        """Assemble the analytical query from all registries.

        Always returns a non-empty ``SQL`` object.  Raises
        ``NotImplementedError`` if ``_get_select_fields`` or ``_get_from_tables``
        are empty — those two registries are mandatory.

        Do not override this method.  Override the registry hooks instead.
        """
        select = self._select()
        from_clause = self._from()
        cte = self._with_cte()
        where = self._where()
        group_by = self._group_by()
        order_by = self._order_by()

        parts = []
        if cte:
            parts.append(SQL("WITH %s", cte))
        parts.extend([select, from_clause])
        parts.extend(clause for clause in (where, group_by, order_by) if clause)
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
        return self._build_table_query()

    def _query(self):
        """Return the assembled SQL for materialized-view creation.

        Called by ``materialized.view.mixin._create_materialized_view``.
        Always returns the assembled query (independent of ``_materialized``
        — this is the SQL that DEFINES the MV, not what the ORM reads from it).
        """
        return self._build_table_query()

    # ------------------------------------------------------------------
    # BUILDER METHODS (do not override)
    # ------------------------------------------------------------------

    def _with_cte(self) -> SQL:
        """Common Table Expression (body only, no WITH keyword).

        Default empty.  Override to return ``SQL("cte_name AS (...), ...")``.
        """
        return SQL.EMPTY

    def _select(self) -> SQL:
        """Build the ``SELECT`` clause from the field registry."""
        fields = self._get_select_fields()
        if not fields:
            raise NotImplementedError(
                f"{self._name}: override _get_select_fields() to return a "
                "non-empty {field_name: sql_expression} mapping."
            )
        field_parts = []
        for field_name, expression in fields.items():
            self._check_percent_escaping(expression, f"select[{field_name!r}]")
            field_parts.append(
                SQL("%s AS %s", SQL(expression), SQL.identifier(field_name)),
            )
        return SQL("SELECT\n    %s", SQL(",\n    ").join(field_parts))

    def _from(self) -> SQL:
        """Build the ``FROM`` clause from the table registry."""
        tables = self._get_from_tables()
        if not tables:
            raise NotImplementedError(
                f"{self._name}: override _get_from_tables() to return a "
                "non-empty list of (table, alias, join_type, on_condition) tuples."
            )
        from_parts = []
        for table_name, alias, join_type, on_condition in tables:
            from_parts.append(
                self._build_from_entry(table_name, alias, join_type, on_condition)
            )
        return SQL("FROM\n    %s", SQL("\n    ").join(from_parts))

    def _build_from_entry(self, table_name, alias, join_type, on_condition) -> SQL:
        """Render a single ``(table, alias, join_type, on)`` entry.

        Base table (``join_type is None``) → ``<table> [<alias>]``.
        JOIN entry → ``<join_type> <table> [<alias>] [ON <condition>]``.
        When ``table_name`` is a ``SQL`` object (e.g. a currency-rate CTE) its
        alias is assumed to be embedded already and the ``alias`` argument is
        ignored on JOIN entries.
        """
        is_sql_obj = isinstance(table_name, SQL)
        if not is_sql_obj:
            self._check_percent_escaping(table_name, "from-table")
        if alias:
            self._check_percent_escaping(alias, "from-alias")
        if join_type is None:
            table_sql = table_name if is_sql_obj else SQL(table_name)
            if alias:
                return SQL("%s %s", table_sql, SQL(alias))
            return table_sql
        if on_condition:
            self._check_percent_escaping(on_condition, f"from-join[{alias!r}]")
        if is_sql_obj:
            if on_condition:
                return SQL("%s %s ON %s", SQL(join_type), table_name, SQL(on_condition))
            return SQL("%s %s", SQL(join_type), table_name)
        table_sql = SQL(table_name)
        alias_sql = SQL(alias) if alias else SQL.EMPTY
        if on_condition:
            return SQL(
                "%s %s %s ON %s",
                SQL(join_type),
                table_sql,
                alias_sql,
                SQL(on_condition),
            )
        return SQL("%s %s %s", SQL(join_type), table_sql, alias_sql)

    def _where(self) -> SQL:
        """Build the ``WHERE`` clause from the condition registry.

        Accepts both strings (wrapped in ``SQL(...)``) and ``SQL`` objects
        (inserted as-is).  Use ``SQL`` objects for parameterized conditions.
        """
        conditions = self._get_where_conditions()
        if not conditions:
            return SQL.EMPTY
        condition_parts = []
        for cond in conditions:
            if isinstance(cond, SQL):
                condition_parts.append(cond)
            else:
                self._check_percent_escaping(cond, "where")
                condition_parts.append(SQL(cond))
        return SQL("WHERE\n    %s", SQL("\n    AND ").join(condition_parts))

    def _group_by(self) -> SQL:
        """Build the ``GROUP BY`` clause from the field registry."""
        fields = self._get_group_by_fields()
        if not fields:
            return SQL.EMPTY
        field_parts = []
        for field in fields:
            self._check_percent_escaping(field, "group_by")
            field_parts.append(SQL(field))
        return SQL("GROUP BY\n    %s", SQL(",\n    ").join(field_parts))

    def _order_by(self) -> SQL:
        """Build the ``ORDER BY`` clause from the field registry.

        Usually the ``_order`` class attribute is what you want — that
        controls Python-side record ordering.  Use this hook only when the
        defining query needs an explicit ``ORDER BY`` at creation time.
        """
        fields = self._get_order_by_fields()
        if not fields:
            return SQL.EMPTY
        field_parts = []
        for field in fields:
            self._check_percent_escaping(field, "order_by")
            field_parts.append(SQL(field))
        return SQL("ORDER BY\n    %s", SQL(",\n    ").join(field_parts))

    # ------------------------------------------------------------------
    # REGISTRY HOOKS (override in subclass)
    # ------------------------------------------------------------------

    def _get_select_fields(self) -> dict:
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
        ``table_name`` may be a string or a ``SQL`` object (e.g. subquery).
        """
        return []

    def _get_where_conditions(self) -> list:
        """Return filter conditions for the WHERE clause.

        Each element may be a string (inserted verbatim) or a ``SQL`` object
        (parameterized).  All conditions are joined with ``AND``.
        """
        return []

    def _get_group_by_fields(self) -> list:
        """Return non-aggregated field expressions for the GROUP BY clause."""
        return []

    def _get_order_by_fields(self) -> list:
        """Return sort expressions for the ORDER BY clause (optional)."""
        return []

    # ------------------------------------------------------------------
    # SAFETY
    # ------------------------------------------------------------------

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
                f"sql.report.mixin: un-escaped '%' in {location}: {expr!r}. "
                "Use '%%' for literal percent (e.g. LIKE '%%x%%')."
            )
