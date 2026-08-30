from odoo.tests import TransactionCase
from odoo.tools.populate import populate_models


class TestPopulate(TransactionCase):
    def _count(self, model):
        return self.env[model].search_count([])

    def test_populate_inherits_model_does_not_raise(self):
        users_before = self._count("res.users")
        partners_before = self._count("res.partner")

        populate_models({self.env["res.users"]: 2}, ord("_"))
        self.env.invalidate_all()

        self.assertEqual(self._count("res.users"), users_before * 3)
        self.assertGreater(self._count("res.partner"), partners_before)

    def test_populate_plain_model(self):
        partners_before = self._count("res.partner")
        populate_models({self.env["res.partner"]: 2}, ord("_"))
        self.env.invalidate_all()
        self.assertEqual(self._count("res.partner"), partners_before * 3)

    def _count_catalogue_probes(self, model_factors):
        cursor_class = type(self.env.cr)
        original = cursor_class.execute
        seen = {"catalogue": 0, "total": 0}

        def counting(cursor, query, *args, **kwargs):
            seen["total"] += 1
            code = getattr(query, "code", None) or (
                query if isinstance(query, str) else ""
            )
            if "pg_index" in code:
                seen["catalogue"] += 1
            return original(cursor, query, *args, **kwargs)

        cursor_class.execute = counting
        try:
            populate_models(model_factors, ord("_"))
        finally:
            cursor_class.execute = original
        return seen

    def test_the_unique_column_lookup_does_not_scale_with_the_columns(self):
        partner = self.env["res.partner"]
        columns = sum(1 for field in partner._fields.values() if field.is_column)
        self.assertGreater(columns, 20, "res.partner should be wide enough to matter")

        seen = self._count_catalogue_probes({partner: 2})

        self.assertLess(
            seen["catalogue"],
            columns // 4,
            f"{seen['catalogue']} pg_index lookups for {columns} columns — the "
            f"per-column probe is back",
        )
        self.assertLess(
            seen["catalogue"],
            seen["total"] // 2,
            "catalogue probing should not dominate a bulk-insert run",
        )
