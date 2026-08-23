{
    "name": "Base SQL Report",
    "version": "19.0.4.0.0",
    "category": "Hidden",
    "summary": "SQL report construction, materialized view and rolling report mixins",
    "description": """
Base SQL Report
===============

Mixins for building SQL-based analytical reports.

``mixin.sql.report``
--------------------
Registry-driven SQL construction for ``_auto = False`` models.  Subclasses
define SELECT / FROM / WHERE / GROUP BY clauses as dicts and lists rather than
monolithic strings; inheritance is just dict / list mutation::

    def _get_fields_select(self):
        fields = super()._get_fields_select()
        fields["margin"] = "SUM(l.margin)"
        return fields

``mixin.materialized.view``
---------------------------
Safe (re)creation and refresh of PostgreSQL materialized views.

* Schema-scoped introspection (``current_schema::regnamespace``).
* RESTRICT-aware drop: warns loudly with the list of dependent relations
  before a CASCADE drop.
* Refuses to silently overwrite a regular table with an MV of the same name.
* ``refresh()`` falls back to blocking REFRESH on unpopulated MVs (PG rejects
  CONCURRENTLY there) and only swallows transient errors — programming errors
  propagate to the cron log.  The REFRESH runs inside a SAVEPOINT so a swallowed
  transient error can't leave the transaction aborted (which would break every
  later statement, e.g. the next MV in a refresh-many cron).
* A default ``init()`` creates the MV from the ``_mv_index_field`` class
  attribute, so concrete models rarely need their own ``init()``.
* ``_create_materialized_view(index_field=...)`` accepts a single column or a
  list/tuple for a composite UNIQUE index.
* ``with_data=True`` by default — PG18 raises ``ObjectNotInPrerequisiteState``
  on SELECT from unpopulated MVs, so the previous default would break queries
  until the first cron tick.

``mixin.rolling.report``
------------------------
A report whose grain is a closed period -- a day, a week -- where only the
newest period can still change.  Stores the report in a real table and rewrites
a trailing window per tick (``DELETE`` then ``INSERT``) instead of re-deriving
every row, which ``REFRESH MATERIALIZED VIEW`` has no way to avoid.

Two rules make the window agree with a full rebuild rather than merely
resemble it, and the mixin's docstring carries the measurements behind both:

* the scan must re-admit each window-function partition's last row from before
  the cutoff, or that partition's first in-window row computes without a
  predecessor;
* the cutoff must land on a grain boundary, or the period it falls inside is
  deleted and re-inserted truncated.

``refresh(full=True)`` rebuilds everything, and ``_rolling_mark_stale()`` is how
a setting that rewrites history asks for that on the next tick.

Composition
-----------
The two mixins compose.  When both are inherited, the ``_materialized`` marker
makes ``sql.report.mixin._table_query`` return ``None`` so the ORM reads the
physical MV — the analytical query is no longer re-inlined as a subquery on
every search.

::

    class MyReport(models.Model):
        _name = "my.report"
        _inherit = ["mixin.sql.report", "mixin.materialized.view"]
        _auto = False

        def _get_fields_select(self): ...
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
