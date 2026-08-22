from odoo.tests import common

from odoo.addons.web.models.record_snapshot import RecordSnapshot

ONCHANGE_LOGGER = "odoo.addons.web.models.web_onchange"


def _count_selects(cr, fn):
    cls = type(cr)
    orig = cls.execute
    n = [0]

    def patched(self, query, params=None, *args, **kwargs):
        code = query if isinstance(query, str) else getattr(query, "code", str(query))
        if str(code).lstrip()[:6].upper() == "SELECT":
            n[0] += 1
        return orig(self, query, params, *args, **kwargs)

    cls.execute = patched
    try:
        fn()
    finally:
        cls.execute = orig
    return n[0]


@common.tagged("post_install", "-at_install", "web_unit", "web_onchange")
class TestOnchange(common.TransactionCase):
    def test_first_call_seeds_defaults(self):
        result = self.env["res.partner"].onchange(
            {}, [], {"name": {}, "active": {}, "company_type": {}}
        )
        self.assertIn("value", result)
        self.assertTrue(result["value"].get("active"))

    def test_field_change_recomputes_dependent(self):
        result = self.env["res.partner"].onchange(
            {"company_type": "company", "is_company": False},
            ["company_type"],
            {"company_type": {}, "is_company": {}},
        )
        self.assertIn("value", result)
        self.assertTrue(
            result["value"].get("is_company"),
            "onchange must recompute is_company from company_type",
        )

    def test_unknown_changed_field_is_dropped_not_fatal(self):
        with self.assertLogs(ONCHANGE_LOGGER, "WARNING") as capture:
            result = self.env["res.partner"].onchange(
                {"company_type": "company", "is_company": False},
                ["company_type", "field_that_does_not_exist"],
                {"company_type": {}, "is_company": {}},
            )
        self.assertIn("field_that_does_not_exist", capture.output[0])
        self.assertIn("value", result)
        self.assertTrue(
            result["value"].get("is_company"),
            "a valid changed field must still recompute despite an unknown name",
        )

    def test_all_unknown_changed_fields_is_noop(self):
        with self.assertLogs(ONCHANGE_LOGGER, "WARNING") as capture:
            result = self.env["res.partner"].onchange(
                {"company_type": "company"},
                ["field_that_does_not_exist"],
                {"company_type": {}, "is_company": {}},
            )
        self.assertIn("field_that_does_not_exist", capture.output[0])
        self.assertEqual(result, {})

    def test_snapshot_diff_link_lines_are_batched(self):
        Partner = self.env["res.partner"]
        spec = {"child_ids": {"fields": {"name": {}, "email": {}, "phone": {}}}}

        def diff_queries(n):
            kids = Partner.create([{"name": f"kid{i}"} for i in range(n)])
            parent = Partner.new({"child_ids": [(6, 0, kids.ids)]})
            snap = RecordSnapshot(parent, spec)
            empty = RecordSnapshot(Partner.new({}), spec, fetch=False)
            self.env.invalidate_all()
            queries = _count_selects(self.env.cr, lambda: snap.diff(empty))
            result = snap.diff(empty)
            link_cmds = [c for c in result.get("child_ids", []) if c[0] == 4]
            self.assertEqual(len(link_cmds), n, "one LINK command per linked line")
            return queries

        few = diff_queries(3)
        many = diff_queries(12)
        self.assertEqual(
            few,
            many,
            f"diff query count scales with link lines (N+1): {few} vs {many}",
        )

    def test_stale_top_level_spec_field_dropped(self):
        with self.assertLogs(ONCHANGE_LOGGER, "WARNING") as capture:
            result = self.env["res.partner"].onchange(
                {"company_type": "company", "is_company": False},
                ["company_type"],
                {"company_type": {}, "is_company": {}, "stale_field_zz": {}},
            )
        self.assertIn("stale_field_zz", capture.output[0])
        self.assertIn("value", result)
        self.assertTrue(result["value"].get("is_company"))
        self.assertNotIn("stale_field_zz", result["value"])

    def test_stale_sub_spec_field_dropped(self):
        Partner = self.env["res.partner"]
        child = Partner.create({"name": "OC Sub Child"})
        parent = Partner.create({"name": "OC Sub Parent", "child_ids": [(4, child.id)]})
        with self.assertLogs(ONCHANGE_LOGGER, "WARNING") as capture:
            result = parent.onchange(
                {"name": "Renamed", "child_ids": [[4, child.id, False]]},
                ["name"],
                {
                    "name": {},
                    "child_ids": {"fields": {"name": {}, "stale_sub_zz": {}}},
                },
            )
        self.assertIn("stale_sub_zz", capture.output[0])
        self.assertIn("value", result)

    def test_first_call_stale_spec_dropped(self):
        with self.assertLogs(ONCHANGE_LOGGER, "WARNING") as capture:
            result = self.env["res.partner"].onchange(
                {}, [], {"name": {}, "active": {}, "stale_first_zz": {}}
            )
        self.assertIn("stale_first_zz", capture.output[0])
        self.assertIn("value", result)
        self.assertTrue(result["value"].get("active"))
        self.assertNotIn("stale_first_zz", result["value"])

    def test_changed_field_absent_from_values_does_not_crash(self):
        result = self.env["res.partner"].onchange(
            {"company_type": "company", "is_company": False},
            ["company_type", "name"],
            {"company_type": {}, "is_company": {}, "name": {}},
        )
        self.assertIn("value", result)
        self.assertTrue(
            result["value"].get("is_company"),
            "valid changed fields must still recompute when another changed "
            "field is absent from values",
        )
