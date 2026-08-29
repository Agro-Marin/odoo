{
    "name": "Base SQL Report",
    "version": "19.0.6.0.0",
    "category": "Hidden",
    "summary": "SQL report construction, materialized view and rolling report mixins",
    "description": """
Base SQL Report
===============

Three composable mixins for ``_auto = False`` analytical reports.

* ``mixin.sql.report`` — builds the query from registries (dicts and lists)
  instead of monolithic SQL strings, so inheritance is dict / list mutation.
* ``mixin.materialized.view`` — owns a physical relation at ``self._table``:
  creates it, indexes it, hashes its definition, and refreshes it from a cron.
* ``mixin.rolling.report`` — the same, for a report whose grain is a closed
  period: stores a real table and rewrites only a trailing window per tick.

Each module file carries the design argument, the measurements behind it, and
the traps — read those rather than a summary here, which is how this
description came to name two models that no longer exist.
    """,
    "author": "AgroMarin",
    "website": "https://www.agromarin.mx",
    "license": "LGPL-3",
    "depends": ["base"],
}
