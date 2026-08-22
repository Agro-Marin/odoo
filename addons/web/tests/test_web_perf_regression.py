from odoo.fields import Command
from odoo.tests.common import TransactionCase, tagged, warmup


@tagged("post_install", "-at_install", "web_perf")
class TestWebPerfRegression(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = cls.env["res.company"].create({"name": "PerfTest Company"})
        cls.user = cls.env["res.users"].create(
            {
                "login": "web_perf",
                "name": "Web Perf User",
                "email": "web_perf@test.example.com",
                "tz": "UTC",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [
                    Command.set(
                        [
                            cls.env.ref("base.group_user").id,
                            cls.env.ref("base.group_partner_manager").id,
                        ]
                    )
                ],
            }
        )

        cls.categories = cls.env["res.partner.category"].create(
            [{"name": f"PerfCat_{i}"} for i in range(5)]
        )

        cls.country_be = cls.env.ref("base.be")

        cls.partners = cls.env["res.partner"].create(
            [
                {
                    "name": f"PerfPartner_{i:03d}",
                    "email": f"perf{i}@test.example.com",
                    "country_id": cls.country_be.id,
                    "category_id": [(6, 0, cls.categories[:3].ids)],
                    "type": "contact",
                    "company_type": "person",
                }
                for i in range(100)
            ]
        )

        cls.parent_partner = cls.env["res.partner"].create(
            {
                "name": "PerfParent",
                "country_id": cls.country_be.id,
            }
        )
        cls.child_partners = cls.env["res.partner"].create(
            [
                {
                    "name": f"PerfChild_{i}",
                    "parent_id": cls.parent_partner.id,
                    "country_id": cls.country_be.id,
                }
                for i in range(10)
            ]
        )

        cls.test_menus = cls.env["ir.ui.menu"].create(
            [{"name": f"PerfMenu_{i}", "sequence": i * 10} for i in range(10)]
        )

        layout_view = cls.env["ir.ui.view"].search([], limit=1)
        cls.test_layouts = cls.env["report.layout"].create(
            [
                {
                    "name": f"PerfLayout_{i}",
                    "sequence": i * 10,
                    "view_id": layout_view.id,
                }
                for i in range(10)
            ]
        )

    def setUp(self):
        super().setUp()
        self.env = self.env(user=self.user)

    @warmup
    def test_web_read_basic(self):
        partners = self.partners.with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(2):
            partners.web_read({"name": {}, "email": {}, "type": {}})

    @warmup
    def test_web_read_many2one_subfields(self):
        partners = self.partners.with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(4):
            partners.web_read(
                {
                    "name": {},
                    "country_id": {
                        "fields": {
                            "display_name": {},
                            "code": {},
                        },
                    },
                }
            )

    @warmup
    def test_web_read_x2many_subfields(self):
        parent = self.parent_partner.with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(5):
            parent.web_read(
                {
                    "name": {},
                    "child_ids": {
                        "fields": {
                            "name": {},
                            "email": {},
                            "country_id": {"fields": {"display_name": {}}},
                        },
                    },
                }
            )

    @warmup
    def test_web_read_many2many_subfields(self):
        partners = self.partners.with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(4):
            partners.web_read(
                {
                    "name": {},
                    "category_id": {
                        "fields": {
                            "display_name": {},
                            "color": {},
                        },
                    },
                }
            )

    @warmup
    def test_web_search_read(self):
        Partners = self.env["res.partner"].with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(4):
            Partners.web_search_read(
                domain=[("name", "like", "PerfPartner")],
                specification={"name": {}, "email": {}, "country_id": {}},
                limit=80,
            )

    @warmup
    def test_web_read_group_single(self):
        Partners = self.env["res.partner"].with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(3):
            Partners.web_read_group(
                domain=[("name", "like", "PerfPartner")],
                groupby=["country_id"],
                aggregates=["__count"],
            )

    @warmup
    def test_web_read_group_auto_unfold(self):
        Partners = self.env["res.partner"].with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(5):
            Partners.web_read_group(
                domain=[("name", "like", "PerfPartner")],
                groupby=["country_id"],
                aggregates=["__count"],
                auto_unfold=True,
                unfold_read_specification={"name": {}, "email": {}},
            )

    @warmup
    def test_search_panel_m2o(self):
        Partners = self.env["res.partner"].with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(3):
            Partners.search_panel_select_range(
                "country_id",
                search_domain=[("name", "like", "PerfPartner")],
                enable_counters=True,
            )

    @warmup
    def test_search_panel_m2m_counters(self):
        Partners = self.env["res.partner"].with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(5):
            Partners.search_panel_select_multi_range(
                "category_id",
                search_domain=[("name", "like", "PerfPartner")],
                enable_counters=True,
            )

    @warmup
    def test_web_name_search(self):
        Partners = self.env["res.partner"].with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(4):
            Partners.web_name_search(
                "PerfPartner",
                specification={"display_name": {}},
                limit=100,
            )

    @warmup
    def test_web_save_multi(self):
        if (
            self.env["ir.module.module"]
            .sudo()
            .search_count([("name", "=like", r"test\_%"), ("state", "=", "installed")])
        ):
            self.skipTest(
                "query pin calibrated for base+web; framework test modules "
                "add res.partner dependents that widen per-write searches"
            )
        partners = (
            self.partners[:10].with_user(self.user).with_context(tracking_disable=True)
        )
        vals_list = [{"name": f"Updated_{i}"} for i in range(10)]
        self.env.invalidate_all()
        with self.assertQueryCount(35):
            partners.web_save_multi(vals_list, specification={"name": {}})

    @warmup
    def test_web_resequence_fast_path(self):
        layouts = self.test_layouts.with_user(self.env.ref("base.user_admin"))
        self.env.invalidate_all()
        with self.assertQueryCount(2):
            layouts.web_resequence(
                specification={"name": {}, "sequence": {}},
                field_name="sequence",
            )

    @warmup
    def test_web_resequence_write_override(self):
        menus = self.test_menus.with_user(self.env.ref("base.user_admin"))
        self.env.invalidate_all()
        with self.assertQueryCount(25):
            menus.web_resequence(
                specification={"name": {}, "sequence": {}},
                field_name="sequence",
            )
