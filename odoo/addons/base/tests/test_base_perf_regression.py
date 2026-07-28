"""Query-count regression tests for base module N+1 optimizations.

Each test pins the expected SQL query count for an optimized path; an N+1
regression fails the test with a higher count.
"""

import traceback

from odoo.tests.common import TransactionCase, tagged, warmup


@tagged("post_install", "-at_install", "base_perf")
class TestBasePerfRegression(TransactionCase):
    """Pin query counts for optimized base module methods."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.partners = cls.env["res.partner"].create(
            [
                {"name": f"PerfPartner_{i}", "barcode": f"PERF-BC-{i:04d}"}
                for i in range(10)
            ]
        )

        cls.vat_partners = cls.env["res.partner"].create(
            [
                {
                    "name": f"VATPartner_{i}",
                    "vat": f"BE099900{i:04d}",
                    "country_id": cls.env.ref("base.be").id,
                }
                for i in range(5)
            ]
        )

        cls.server_actions = cls.env["ir.actions.server"].create(
            [
                {
                    "name": f"PerfAction_{i}",
                    "model_id": cls.env.ref("base.model_res_partner").id,
                    "state": "code",
                    "code": f"record.write({{'name': 'v{i}'}})",
                }
                for i in range(5)
            ]
        )
        cls.env["ir.actions.server.history"].create(
            [
                {
                    "action_id": action.id,
                    "code": f"# old code for {action.name}",
                }
                for action in cls.server_actions
            ]
        )

        cls.window_actions = cls.env["ir.actions.act_window"].create(
            [
                {
                    "name": f"PerfWindow_{i}",
                    "res_model": "res.partner",
                    "path": f"perf-path-{i}",
                }
                for i in range(10)
            ]
        )

    @warmup
    def test_check_path_batch(self):
        """Path constraint uses 1 grouped _read_group, not N search_counts."""
        actions = self.window_actions
        self.env.invalidate_all()
        with self.assertQueryCount(2):
            actions._check_path()

    @warmup
    def test_check_barcode_batch(self):
        """Barcode constraint uses 1 search_fetch, not N search_counts."""
        partners = self.partners
        self.env.invalidate_all()
        with self.assertQueryCount(2):
            partners._check_barcode_unicity()

    @warmup
    def test_compute_show_code_history(self):
        """Code history compute uses 1 search_fetch, not N search_counts."""
        actions = self.server_actions
        self.env.invalidate_all()
        with self.assertQueryCount(9):
            actions._compute_show_code_history()

    @warmup
    def test_get_bindings_cold_cache(self):
        """First bindings load does batch reads per action type, not per action."""
        Actions = self.env["ir.actions.actions"]
        self.registry.clear_all_caches()
        self.env.invalidate_all()
        with self.assertQueryCount(10):
            Actions._get_bindings("res.partner")

    @warmup
    def test_compute_partner_share(self):
        """Partner share compute uses 1 _read_group, not N per-partner checks."""
        partners = self.partners
        self.env.invalidate_all()
        with self.assertQueryCount(4):
            partners._compute_partner_share()

    @warmup
    def test_compute_is_public(self):
        """Public compute queries group membership directly, not per partner."""
        partners = self.partners
        self.env.invalidate_all()
        with self.assertQueryCount(6):
            partners._compute_is_public()

    @warmup
    def test_compute_main_user_id(self):
        """Main user compute uses 1 batch search_fetch, not per-partner user_ids."""
        partners = self.partners
        self.env.invalidate_all()
        with self.assertQueryCount(5):
            partners._compute_main_user_id()

    @warmup
    def test_compute_same_vat(self):
        """Same VAT compute pre-filters with _read_group, skips unique VATs."""
        partners = self.vat_partners
        self.env.invalidate_all()
        with self.assertQueryCount(10):
            partners._compute_same_vat_partner_id()

    @warmup
    def test_selection_target_model_cached(self):
        """Second call to _selection_target_model hits ormcache → 0 queries."""
        ServerAction = self.env["ir.actions.server"]
        ServerAction._selection_target_model()
        self.env.invalidate_all()
        with self.assertQueryCount(0):
            ServerAction._selection_target_model()

    @warmup
    def test_ir_model_view_ids(self):
        """View IDs compute uses 1 batch search, not N per-model searches."""
        ir_models = self.env["ir.model"].search([], limit=20)
        self.env.invalidate_all()
        with self.assertQueryCount(4):
            ir_models._compute_view_ids()

    @warmup
    def test_ir_model_inherited_models(self):
        """Inherited models compute uses 1 batch search, not N per-model."""
        ir_models = self.env["ir.model"].search([], limit=20)
        self.env.invalidate_all()
        with self.assertQueryCount(5):
            ir_models._compute_inherited_model_ids()

    @warmup
    def test_ir_model_compute_count(self):
        """Record count uses 1 UNION ALL query, not N COUNT(*) per table.

        Read through the field rather than calling ``_compute_count`` directly:
        a compute assigns with ``record.<field> = value``, and outside the
        ``env.protecting`` scope the field machinery sets up that assignment is
        a real :meth:`~odoo.models.Model.write` — which stamps ``write_date``,
        so ``assertQueryCount``'s trailing flush issues an ``UPDATE ir_model``
        the production path never performs.  Measuring the direct call measured
        that UPDATE too (4 rather than 3).
        """
        ir_models = self.env["ir.model"].search([], limit=20)
        self.env.invalidate_all()
        with self.assertQueryCount(3):
            ir_models.mapped("count")

    def test_create_partners_does_not_fetch_per_record(self):
        """Creating N partners must not cost a SELECT per partner for the
        commercial/parent fields the sync helpers read.

        ``_fields_sync`` used to call ``self.fetch([...])`` on the single-record
        ``self`` it receives. ``fetch()`` queries ``self`` alone (``_as_query``)
        and ignores ``_prefetch_ids``, so that was one SELECT per partner --
        the opposite of its intent. Plain attribute access in the helpers does
        honour the prefetch set, so the batch load happens once, for free.

        Counts only the commercial_partner_id SELECT rather than the total, so
        unrelated ORM query-count drift (e.g. the attachment lookups the image
        mixin triggers) cannot make this test flap.
        """
        Partner = self.env["res.partner"]
        cursor_cls = type(self.env.cr)
        original_execute = cursor_cls.execute
        seen = []

        def spy(cr_self, query, params=None, **kwargs):
            code = getattr(query, "code", None) or str(query)
            if '"commercial_partner_id" FROM "res_partner"' in code:
                seen.append(code)
            return original_execute(cr_self, query, params, **kwargs)

        self.env.invalidate_all()
        cursor_cls.execute = spy
        try:
            Partner.create([{"name": f"PerfCreate_{i}"} for i in range(20)])
            self.env.flush_all()
        finally:
            cursor_cls.execute = original_execute

        self.assertLessEqual(
            len(seen),
            1,
            f"expected at most 1 commercial_partner_id SELECT for a 20-partner "
            f"create, got {len(seen)}",
        )

    def test_create_records_with_images_batches_attachment_lookups(self):
        """Creating N records of an image.mixin model must not cost one
        ir_attachment SELECT per record per resized image field.

        ``Field._compute_related`` assigned the related value one record at a
        time. Attachment-backed ``Binary.mark_dirty`` runs an ir_attachment
        search per assignment, so propagating the 4 stored resized image fields
        cost 4*N SELECTs (each returning nothing) on a plain create. Records
        receiving the same falsy value are now assigned in one go.
        """
        Partner = self.env["res.partner"]
        cursor_cls = type(self.env.cr)
        original_execute = cursor_cls.execute
        seen = []

        def spy(cr_self, query, params=None, **kwargs):
            code = getattr(query, "code", None) or str(query)
            if (
                'FROM "ir_attachment"' in code
                and '"res_field"' in code
                and "res.partner" in str(params)
            ):
                caller = [
                    f"{frame.filename.rsplit('/odoo/', 1)[-1]}:{frame.lineno}"
                    for frame in traceback.extract_stack()[:-1]
                    if "/addons/" in frame.filename or "/orm/fields/" in frame.filename
                ]
                seen.append(" <- ".join(reversed(caller[-4:])))
            return original_execute(cr_self, query, params, **kwargs)

        self.env.invalidate_all()
        cursor_cls.execute = spy
        try:
            Partner.create([{"name": f"PerfImg_{i}"} for i in range(20)])
            self.env.flush_all()
        finally:
            cursor_cls.execute = original_execute

        self.assertLessEqual(
            len(seen),
            4,
            f"expected at most 4 ir_attachment lookups for a 20-record create, "
            f"got {len(seen)}:\n  " + "\n  ".join(seen),
        )
