{
    "name": "Base SQL Report",
    "version": "19.0.2.0.0",
    "category": "Hidden",
    "summary": "SQL report construction and materialized view mixins",
    "description": """
Base SQL Report
===============

Mixins for building SQL-based analytical reports.

``sql.report.mixin``
--------------------
Registry-driven SQL construction for ``_auto = False`` models.  Subclasses
define SELECT / FROM / WHERE / GROUP BY clauses as dicts and lists rather than
monolithic strings; inheritance is just dict / list mutation::

    def _get_select_fields(self):
        fields = super()._get_select_fields()
        fields["margin"] = "SUM(l.margin)"
        return fields

``materialized.view.mixin``
---------------------------
Safe (re)creation and refresh of PostgreSQL materialized views.

* Schema-scoped introspection (``current_schema::regnamespace``).
* RESTRICT-aware drop: warns loudly with the list of dependent relations
  before a CASCADE drop.
* Refuses to silently overwrite a regular table with an MV of the same name.
* ``refresh()`` falls back to blocking REFRESH on unpopulated MVs (PG rejects
  CONCURRENTLY there) and only swallows transient errors — programming errors
  propagate to the cron log.
* ``with_data=True`` by default — PG18 raises ``ObjectNotInPrerequisiteState``
  on SELECT from unpopulated MVs, so the previous default would break queries
  until the first cron tick.

Composition
-----------
The two mixins compose.  When both are inherited, the ``_materialized`` marker
makes ``sql.report.mixin._table_query`` return ``None`` so the ORM reads the
physical MV — the analytical query is no longer re-inlined as a subquery on
every search.

::

    class MyReport(models.Model):
        _name = "my.report"
        _inherit = ["sql.report.mixin", "materialized.view.mixin"]
        _auto = False

        def _get_select_fields(self): ...
        def _get_from_tables(self): ...

        def init(self):
            self._create_materialized_view(index_field="product_id")

Trust contract
--------------
Registry values are inserted into SQL verbatim.  Never build them from
``self.env.context`` or other untrusted sources.  For parameterized
conditions, return an ``SQL`` object from ``_get_where_conditions`` —
e.g. ``SQL("o.partner_id = %s", pid)``.
    """,
    "author": "AgroMarin",
    "website": "https://www.agromarin.mx",
    "license": "LGPL-3",
    "depends": ["base"],
}
