{
    "name": "Test - SQL Report Mixins",
    "version": "19.0.1.0.0",
    "category": "Hidden/Tests",
    "summary": "Concrete consumers of the SQL report mixins, for their tests",
    "description": """
Test - SQL Report Mixins
========================

The three mixins in ``mixin_report_sql`` are abstract, and the defects they
shipped with were all invisible to a suite that patched them in place: a
stand-alone model's own ``_table_query`` shadows a mixin property, a missing
``id`` index only exists once a relation is really created, and a rolling
window only reaches its column list on the *second* tick. None of that can be
reached without real models, so the models live here and this module is
installed by the test lane and by nobody else.
    """,
    "author": "AgroMarin",
    "license": "LGPL-3",
    "depends": [
        "mixin_report_sql",
    ],
    "installable": True,
}
