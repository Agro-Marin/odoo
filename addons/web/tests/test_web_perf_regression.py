"""Query count regression tests for web module operations.

Each test pins the expected number of SQL queries for an optimized code path.
If a future change introduces an N+1 regression, the test will fail with a
higher-than-expected query count.

Run with:
    > ./odoo.log && ./core/odoo-bin -c ./conf/odoo.conf -d test_db \
        --test-tags '/web:TestWebPerfRegression' -u web \
        --stop-after-init --workers=0
    grep "tests when loading" ./odoo.log
"""

from odoo.fields import Command
from odoo.tests.common import TransactionCase, tagged, warmup


@tagged("post_install", "-at_install", "web_perf")
class TestWebPerfRegression(TransactionCase):
    """Pin query counts for web module CRUD operations."""

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
        """web_read: 100 records, flat spec (name + email + type)."""
        partners = self.partners.with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(2):
            partners.web_read({"name": {}, "email": {}, "type": {}})


    @warmup
    def test_web_read_many2one_subfields(self):
        """web_read: 100 records with many2one (country_id) sub-spec."""
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
        """web_read: parent + 10 children with one2many sub-spec."""
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
        """web_read: 100 records with many2many (category_id) sub-spec."""
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
        """web_search_read: domain match ~100, limit=80 (triggers count)."""
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
        """web_read_group: group by country_id, no auto_unfold."""
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
        """web_read_group: group by country_id, auto_unfold=True."""
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
        """search_panel_select_range: many2one (country_id) with counters."""
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
        """search_panel_select_multi_range: m2m (category_id) with counters.

        Batched: single _search_panel_domain_image() replaces N search_count().
        """
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
        """web_name_search: display_name-only fast path."""
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
        """web_save_multi: write 10 records with unique vals (per-record write)."""
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
        """web_resequence: 10 records on a fast-path-eligible model.

        report.layout does not override write() and its ``sequence`` is a
        plain stored Integer (no compute/inverse), so web_resequence takes the
        cache-dirty fast path: access checks once, mark_dirty loop, a single
        modified(), and one batched UPDATE at flush time.
        """
        layouts = self.test_layouts.with_user(self.env.ref("base.user_admin"))
        self.env.invalidate_all()
        with self.assertQueryCount(2):
            layouts.web_resequence(
                specification={"name": {}, "sequence": {}},
                field_name="sequence",
            )

    @warmup
    def test_web_resequence_write_override(self):
        """web_resequence: 10 menu items through the per-record write() path.

        ir.ui.menu overrides write() (each real write clears the registry-wide
        ormcaches, because the menu caches depend on ``sequence``), so the
        cache-dirty fast path may NOT apply: skipping write() would leave stale
        menu caches after a drag-reorder. The documented cost of honoring the
        override is therefore per-record:

        - 1  group-ids reload (the warmup run's cache clears wiped it)
        - 20 = 10 x (ACL perm_write + ir.rule perm_write): each write()'s
          registry cache clear wipes the access ormcaches the previous
          iteration just re-warmed
        - 2  ACL perm_read + ir.rule perm_read for the final web_read
        - 1  web_read SELECT
        - 1  single batched UPDATE at flush (the writes themselves are
          deferred and flushed together — the N+1 is the access-cache
          reloading, not the UPDATE)

        In real usage the client only sends the records whose sequence value
        actually changes (see computeResequencePlan in
        static/src/model/relational_model/resequence.js), so this cost scales
        with the size of the move, not the size of the list.
        """
        menus = self.test_menus.with_user(self.env.ref("base.user_admin"))
        self.env.invalidate_all()
        with self.assertQueryCount(25):
            menus.web_resequence(
                specification={"name": {}, "sequence": {}},
                field_name="sequence",
            )
