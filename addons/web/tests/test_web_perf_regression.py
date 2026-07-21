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

        # Dedicated company + user for stable query counts
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

        # ir.ui.menu has a native sequence field, needed by web_resequence.
        # It also overrides write() (registry-wide cache clear), which forces
        # web_resequence onto its per-record write() slow path.
        cls.test_menus = cls.env["ir.ui.menu"].create(
            [{"name": f"PerfMenu_{i}", "sequence": i * 10} for i in range(10)]
        )

        # report.layout has a plain stored Integer sequence, no write()
        # override anywhere in the addons tree, and is admin-writable
        # (group_system): it qualifies for web_resequence's cache-dirty
        # fast path.
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

    # ------------------------------------------------------------------
    # web_read: flat specification
    # ------------------------------------------------------------------

    @warmup
    def test_web_read_basic(self):
        """web_read: 100 records, flat spec (name + email + type)."""
        partners = self.partners.with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(2):
            # 1 read (fields) + access rules
            partners.web_read({"name": {}, "email": {}, "type": {}})

    # ------------------------------------------------------------------
    # web_read: many2one with sub-fields
    # ------------------------------------------------------------------

    @warmup
    def test_web_read_many2one_subfields(self):
        """web_read: 100 records with many2one (country_id) sub-spec."""
        partners = self.partners.with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(4):
            # 1 read (partner fields) + 1 read (country co-records)
            # + 1 sudo read (display_name) + access rules
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

    # ------------------------------------------------------------------
    # web_read: one2many with sub-fields
    # ------------------------------------------------------------------

    @warmup
    def test_web_read_x2many_subfields(self):
        """web_read: parent + 10 children with one2many sub-spec."""
        parent = self.parent_partner.with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(5):
            # 1 flush + 1 read (parent) + 1 read (child co-records)
            # + access rules
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

    # ------------------------------------------------------------------
    # web_read: many2many with sub-fields
    # ------------------------------------------------------------------

    @warmup
    def test_web_read_many2many_subfields(self):
        """web_read: 100 records with many2many (category_id) sub-spec."""
        partners = self.partners.with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(4):
            # 1 read (partner fields incl. m2m rel table)
            # + 1 read (category co-records) + access rules
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

    # ------------------------------------------------------------------
    # web_search_read
    # ------------------------------------------------------------------

    @warmup
    def test_web_search_read(self):
        """web_search_read: domain match ~100, limit=80 (triggers count)."""
        Partners = self.env["res.partner"].with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(4):
            # 1 search + 1 fetch + 1 read + 1 count
            Partners.web_search_read(
                domain=[("name", "like", "PerfPartner")],
                specification={"name": {}, "email": {}, "country_id": {}},
                limit=80,
            )

    # ------------------------------------------------------------------
    # web_read_group: single level, no unfold
    # ------------------------------------------------------------------

    @warmup
    def test_web_read_group_single(self):
        """web_read_group: group by country_id, no auto_unfold."""
        Partners = self.env["res.partner"].with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(3):
            # 1 flush + 1 _read_group + 1 access rules
            Partners.web_read_group(
                domain=[("name", "like", "PerfPartner")],
                groupby=["country_id"],
                aggregates=["__count"],
            )

    # ------------------------------------------------------------------
    # web_read_group: with auto_unfold
    # ------------------------------------------------------------------

    @warmup
    def test_web_read_group_auto_unfold(self):
        """web_read_group: group by country_id, auto_unfold=True."""
        Partners = self.env["res.partner"].with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(5):
            # _read_group + per-group search + union web_read + count
            Partners.web_read_group(
                domain=[("name", "like", "PerfPartner")],
                groupby=["country_id"],
                aggregates=["__count"],
                auto_unfold=True,
                unfold_read_specification={"name": {}, "email": {}},
            )

    # ------------------------------------------------------------------
    # search_panel_select_range: many2one with counters
    # ------------------------------------------------------------------

    @warmup
    def test_search_panel_m2o(self):
        """search_panel_select_range: many2one (country_id) with counters."""
        Partners = self.env["res.partner"].with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(3):
            # 1 _read_group (image) + 1 _read_group (count) + access rules
            Partners.search_panel_select_range(
                "country_id",
                search_domain=[("name", "like", "PerfPartner")],
                enable_counters=True,
            )

    # ------------------------------------------------------------------
    # search_panel_select_multi_range: many2many with counters (N+1)
    # ------------------------------------------------------------------

    @warmup
    def test_search_panel_m2m_counters(self):
        """search_panel_select_multi_range: m2m (category_id) with counters.

        Batched: single _search_panel_domain_image() replaces N search_count().
        """
        Partners = self.env["res.partner"].with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(5):
            # 1 domain_image + 1 search_read + 1 count_image + access rules
            Partners.search_panel_select_multi_range(
                "category_id",
                search_domain=[("name", "like", "PerfPartner")],
                enable_counters=True,
            )

    # ------------------------------------------------------------------
    # web_name_search: display_name-only fast path
    # ------------------------------------------------------------------

    @warmup
    def test_web_name_search(self):
        """web_name_search: display_name-only fast path."""
        Partners = self.env["res.partner"].with_user(self.user)
        self.env.invalidate_all()
        with self.assertQueryCount(4):
            # 1 name_search + 1 exists() guard (concurrent-unlink hardening in
            # web_name_search's display_name fast path) + 1 browse/read
            # + access rules
            Partners.web_name_search(
                "PerfPartner",
                specification={"display_name": {}},
                limit=100,
            )

    # ------------------------------------------------------------------
    # web_save_multi (N+1: per-record write)
    # ------------------------------------------------------------------

    @warmup
    def test_web_save_multi(self):
        """web_save_multi: write 10 records with unique vals (per-record write).

        Records with identical vals are batched into a single write().
        With unique vals (as here), falls back to per-record writes.

        ``tracking_disable`` pins the web-layer cost independently of the
        install set: once mail is installed, res.partner is
        mail.thread-enabled and each tracked write adds one mail.message +
        one mail.tracking.value INSERT per record plus two batched reads
        (35 → 57 measured on base+web+mail). The historical pin of 70 was
        calibrated on such a richer dev database, so it never matched this
        test's own fixture (fresh base+web: 35) and the non-fatal
        undercount had made the pin inert. With tracking disabled the
        count is identical on base+web and base+web+mail (verified
        2026-07-21).
        """
        partners = (
            self.partners[:10].with_user(self.user).with_context(tracking_disable=True)
        )
        vals_list = [{"name": f"Updated_{i}"} for i in range(10)]
        self.env.invalidate_all()
        with self.assertQueryCount(35):
            # 10 unique vals → 10 individual write() calls. Breakdown
            # (recalibrated 2026-07-21 on the fixture this test
            # guarantees — no optimizing commit to cite: the fixture
            # count has been 35 since the pin landed):
            # - 4  batched pre-reads on the first write(): partner
            #   fetch (covers all 10 records via the prefetch set, and
            #   feeds the final web_read from cache), company co-read,
            #   and res.partner.bank / res.users dependent-record
            #   lookups for the display-name dependencies
            # - 30 = 10 x 3 per-record modified() searches — the pinned
            #   N+1: each write() re-resolves the complete_name /
            #   display_name dependents (children by parent_id,
            #   commercial descendants by commercial_partner_id,
            #   companies by partner_id)
            # - 1  single batched UPDATE at flush (name, complete_name,
            #   write_date, write_uid via UPDATE ... FROM (VALUES ...))
            # The final web_read issues 0 queries (served from cache).
            partners.web_save_multi(vals_list, specification={"name": {}})

    # ------------------------------------------------------------------
    # web_resequence: fast path vs write()-override slow path
    # ------------------------------------------------------------------

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
            # 1 flush (single batched UPDATE of the dirty sequences)
            # + 1 web_read
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
