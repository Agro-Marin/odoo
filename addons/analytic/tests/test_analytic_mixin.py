from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestAnalyticMixin(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.analytic_plan = cls.env["account.analytic.plan"].create({"name": "Plan"})

        cls.sales_aa = cls.env["account.analytic.account"].create(
            {"name": "Sales", "plan_id": cls.analytic_plan.id}
        )
        cls.administrative_aa = cls.env["account.analytic.account"].create(
            {"name": "Administrative", "plan_id": cls.analytic_plan.id}
        )
        cls.rd_aa = cls.env["account.analytic.account"].create(
            {"name": "Research & Development", "plan_id": cls.analytic_plan.id}
        )
        cls.commercial_aa = cls.env["account.analytic.account"].create(
            {"name": "Commercial", "plan_id": cls.analytic_plan.id}
        )
        cls.marketing_aa = cls.env["account.analytic.account"].create(
            {"name": "Marketing", "plan_id": cls.analytic_plan.id}
        )
        cls.com_marketing_aa = cls.env["account.analytic.account"].create(
            {"name": "Commercial & Marketing", "plan_id": cls.analytic_plan.id}
        )

    def test_filtered_domain(self):
        """Test the `filtered_domain` override on `analytic.mixin` for every supported operator."""
        # `=`, `!=`, `ilike` and `not ilike` compare against an analytic account name;
        # `in` takes a tuple/list of analytic account ids directly.

        self.adm_sales_admin_ad = self.env[
            "account.analytic.distribution.model"
        ].create(
            {
                "analytic_distribution": {
                    self.sales_aa.id: 50,
                    self.administrative_aa.id: 50,
                }
            }
        )
        self.adm_rd_ad = self.env["account.analytic.distribution.model"].create(
            {
                "analytic_distribution": {self.rd_aa.id: 100},
            }
        )
        self.adm_commercial_ad = self.env["account.analytic.distribution.model"].create(
            {
                "analytic_distribution": {self.commercial_aa.id: 100},
            }
        )
        self.adm_com_marketing_ad = self.env[
            "account.analytic.distribution.model"
        ].create(
            {
                "analytic_distribution": {self.com_marketing_aa.id: 100},
            }
        )
        self.adm_without_ad = self.env["account.analytic.distribution.model"].create({})
        self.adm_without_ad_1 = self.env["account.analytic.distribution.model"].create(
            {}
        )

        adm_ids = self.env["account.analytic.distribution.model"].search([])

        def filter_domain(comparator, value):
            return adm_ids.filtered_domain(
                [("analytic_distribution", comparator, value)]
            )

        self.assertEqual(filter_domain("=", "Research & Development"), self.adm_rd_ad)
        self.assertEqual(filter_domain("=", "Sales"), self.adm_sales_admin_ad)
        self.assertEqual(filter_domain("=", "Administrative"), self.adm_sales_admin_ad)
        self.assertEqual(filter_domain("=", "Commercial"), self.adm_commercial_ad)
        self.assertFalse(filter_domain("=", ""))  # Should return an empty recordset
        self.assertEqual(
            filter_domain("=", self.commercial_aa.id), self.adm_commercial_ad
        )

        self.assertEqual(
            filter_domain("ilike", "Commercial"),
            self.adm_commercial_ad | self.adm_com_marketing_ad,
        )
        self.assertEqual(
            filter_domain("ilike", ""),
            adm_ids - self.adm_without_ad - self.adm_without_ad_1,
        )

        self.assertEqual(
            filter_domain("not ilike", "Commercial"),
            adm_ids - self.adm_com_marketing_ad - self.adm_commercial_ad,
        )
        self.assertEqual(
            filter_domain("not ilike", ""), self.adm_without_ad + self.adm_without_ad_1
        )  # Should return the ADMs without analytic_distribution

        self.assertEqual(
            filter_domain("!=", "Commercial & Marketing"),
            adm_ids - self.adm_com_marketing_ad,
        )
        self.assertEqual(
            filter_domain("!=", ""), adm_ids
        )  # Should return every ADM
        self.assertEqual(
            filter_domain("!=", self.commercial_aa.id), adm_ids - self.adm_commercial_ad
        )

        self.assertEqual(
            filter_domain("in", [self.commercial_aa.id]), self.adm_commercial_ad
        )
        self.assertEqual(
            filter_domain("in", (self.sales_aa + self.rd_aa).ids),
            self.adm_sales_admin_ad + self.adm_rd_ad,
        )

    def test_search_distribution_in_by_account_name(self):
        """Test that `_search_analytic_distribution` accepts a list of account names for `in`."""
        # Regression: the branch tested `isinstance(value, str)` instead of the element
        # `v`, so a list of names silently matched nothing.
        ADM = self.env["account.analytic.distribution.model"]
        sales_adm = ADM.create({"analytic_distribution": {self.sales_aa.id: 100}})
        rd_adm = ADM.create({"analytic_distribution": {self.rd_aa.id: 100}})

        self.assertEqual(
            ADM.search(
                [
                    ("id", "in", (sales_adm + rd_adm).ids),
                    ("analytic_distribution", "in", ["Sales"]),
                ]
            ),
            sales_adm,
        )
        self.assertEqual(
            ADM.search(
                [
                    ("id", "in", (sales_adm + rd_adm).ids),
                    (
                        "analytic_distribution",
                        "in",
                        ["Sales", "Research & Development"],
                    ),
                ]
            ),
            sales_adm + rd_adm,
        )

    def test_update_marker_not_persisted_on_plain_mixin(self):
        """A model that does not consume the transient `__update__` marker must never persist it."""
        # Regression: the marker leaked into the stored JSON and later made
        # `int('__update__')` raise across every key reader.
        ADM = self.env["account.analytic.distribution.model"]
        self.assertFalse(ADM._analytic_distribution_consumes_update())

        adm = ADM.create(
            {
                "analytic_distribution": {
                    f"{self.sales_aa.id}": 100,
                    "__update__": ["x_plan1_id"],
                }
            }
        )
        adm.flush_recordset()
        self.env.cr.execute(
            "SELECT analytic_distribution FROM account_analytic_distribution_model WHERE id = %s",
            [adm.id],
        )
        stored = self.env.cr.fetchone()[0]
        self.assertNotIn(
            "__update__", stored, "the transient marker must be stripped before storage"
        )
        self.assertEqual(stored, {str(self.sales_aa.id): 100})

        # A write path must strip it too, not only create.
        adm.write(
            {
                "analytic_distribution": {
                    f"{self.rd_aa.id}": 100,
                    "__update__": ["x_plan1_id"],
                }
            }
        )
        adm.flush_recordset()
        self.assertNotIn("__update__", adm.analytic_distribution)

    def test_account_ids_from_distribution_is_robust(self):
        """The key parser tolerates the `__update__` marker and malformed segments, and de-duplicates in order."""
        mixin = self.env["analytic.mixin"]
        s, r = self.sales_aa.id, self.rd_aa.id
        self.assertEqual(
            mixin._account_ids_from_distribution(
                {f"{s},{r}": 100, "__update__": ["x"]}
            ),
            [s, r],
        )
        self.assertEqual(
            mixin._account_ids_from_distribution({f"{s},": 100, f" {r} ": 50}), [s, r]
        )
        self.assertEqual(
            mixin._account_ids_from_distribution({f"{s},{r}": 50, f"{r}": 50}), [s, r]
        )
        self.assertEqual(mixin._account_ids_from_distribution({}), [])
        # aggregate helper: accepts a single dict or an iterable of dicts, returns a set, never raises
        self.assertEqual(
            mixin._get_analytic_account_ids_from_distributions(
                {f"{s}": 100, "__update__": ["x"]}
            ),
            {s},
        )
        self.assertEqual(
            mixin._get_analytic_account_ids_from_distributions(
                [{f"{s}": 100}, {f"{r}": 100, "__update__": ["x"]}]
            ),
            {s, r},
        )

    def test_read_group_by_distribution_defaults_to_self(self):
        """Grouping by `analytic_distribution` with no dedicated count id counts the record itself."""
        # Regression: a hardcoded table map used to raise `ValueError` for any model it
        # did not list (inverted-dependency removal).
        ADM = self.env["account.analytic.distribution.model"]
        made = ADM.create(
            [
                {"analytic_distribution": {self.sales_aa.id: 100}},
                {"analytic_distribution": {self.sales_aa.id: 100}},
                {"analytic_distribution": {self.rd_aa.id: 100}},
            ]
        )
        # grouping by analytic_distribution yields raw account-id keys
        groups = dict(
            ADM._read_group(
                domain=[("id", "in", made.ids)],
                groupby=["analytic_distribution"],
                aggregates=["__count"],
            )
        )
        self.assertEqual(groups.get(self.sales_aa.id), 2)
        self.assertEqual(groups.get(self.rd_aa.id), 1)
