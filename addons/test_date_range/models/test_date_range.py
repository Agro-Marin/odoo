"""Concrete consumer of ``date.range.search.mixin`` used by the tests.

The mixin contributes a virtual ``date_range_search_id`` field and rewrites the
search view of whatever model inherits it, so exercising it needs a real model
with a real date column and a real search view.

It used to be a class declared under ``date_range/tests/models.py`` and pushed
into the registry at ``setUpClass`` time by a vendored copy of OCA's
``FakeModelLoader``. That copy existed only to paper over Odoo 19 renaming
``MetaModel.module_to_models`` to ``_module_to_models__``, and it had to
back up and restore the registry around every run. A fixture addon is what
core does instead — see ``test_resource`` — and it needs none of that.
"""

from odoo import fields, models


class DateRangeSearchTest(models.Model):
    _name = "date.range.search.test"
    _description = "Date Range Search Mixin Test Model"
    _inherit = ["date.range.search.mixin"]
    _date_range_search_field = "test_date"

    name = fields.Char()
    test_date = fields.Date()
