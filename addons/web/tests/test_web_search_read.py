from unittest.mock import patch

from odoo.tests import common

SCREENING_LOGGER = "odoo.addons.web.models.web_onchange"


@common.tagged("post_install", "-at_install", "web_unit", "web_search")
class TestWebSearchRead(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ResCurrency = cls.env["res.currency"].with_context(active_test=False)
        cls.max = cls.ResCurrency.search_count([])

    def assert_web_search_read(
        self,
        expected_length,
        expected_records_length,
        expected_search_count_called=True,
        **kwargs,
    ):
        original_search_count = self.ResCurrency.search_count
        search_count_called = [False]

        def search_count(obj, *method_args, **method_kwargs):
            search_count_called[0] = True
            return original_search_count(*method_args, **method_kwargs)

        with patch(
            "odoo.addons.base.models.res_currency.ResCurrency.search_count",
            new=search_count,
        ):
            results = self.ResCurrency.web_search_read(
                domain=[], specification={"id": {}}, **kwargs
            )

        self.assertEqual(results["length"], expected_length)
        self.assertEqual(len(results["records"]), expected_records_length)
        self.assertEqual(search_count_called[0], expected_search_count_called)

    def test_unity_web_search_read(self):
        self.assert_web_search_read(
            self.max, self.max, expected_search_count_called=False
        )
        self.assert_web_search_read(
            self.max, 2, limit=2, expected_search_count_called=False
        )
        self.assert_web_search_read(
            self.max, 2, limit=2, offset=10, expected_search_count_called=False
        )
        self.assert_web_search_read(
            2, 2, limit=2, count_limit=2, expected_search_count_called=False
        )
        self.assert_web_search_read(
            20,
            2,
            limit=2,
            offset=10,
            count_limit=20,
            expected_search_count_called=False,
        )
        self.assert_web_search_read(
            12,
            2,
            limit=2,
            offset=10,
            count_limit=12,
            expected_search_count_called=False,
        )

    def test_empty_page_past_end_reports_real_length(self):
        self.assertGreater(self.max, 0)
        res = self.ResCurrency.web_search_read(
            domain=[], specification={"id": {}}, offset=self.max + 50, limit=5
        )
        self.assertEqual(res["records"], [])
        self.assertEqual(res["length"], self.max)

        res_empty = self.ResCurrency.web_search_read(
            domain=[("id", "=", -1)], specification={"id": {}}, offset=0, limit=5
        )
        self.assertEqual(res_empty["length"], 0)
        self.assertEqual(res_empty["records"], [])

    def test_web_name_search(self):
        result = self.env["res.partner"].web_name_search("", {"display_name": {}})[0]
        self.assertIn("display_name", result)
        self.assertIn("__formatted_display_name", result)

    def test_stale_specification_key_is_screened(self):
        with self.assertLogs(SCREENING_LOGGER, "WARNING") as capture:
            res = self.env["res.partner"].web_search_read(
                domain=[],
                specification={"id": {}, "display_name": {}, "stale_zz": {}},
                limit=2,
            )
        self.assertIn("stale_zz", capture.output[0])
        self.assertTrue(res["records"])
        for rec in res["records"]:
            self.assertIn("display_name", rec)
            self.assertNotIn("stale_zz", rec)

    def test_stale_sub_specification_key_is_screened(self):
        parent = self.env["res.partner"].create(
            {"name": "WSR Sub Parent", "is_company": True}
        )
        child = self.env["res.partner"].create(
            {"name": "WSR Sub Child", "parent_id": parent.id}
        )
        with self.assertLogs(SCREENING_LOGGER, "WARNING") as capture:
            res = self.env["res.partner"].web_search_read(
                domain=[("id", "=", child.id)],
                specification={
                    "id": {},
                    "parent_id": {"fields": {"display_name": {}, "stale_sub_zz": {}}},
                },
            )
        self.assertIn("stale_sub_zz", capture.output[0])
        [rec] = res["records"]
        self.assertEqual(rec["parent_id"]["display_name"], "WSR Sub Parent")
        self.assertNotIn("stale_sub_zz", rec["parent_id"])
