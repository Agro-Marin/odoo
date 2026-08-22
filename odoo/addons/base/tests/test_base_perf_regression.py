import traceback

from odoo.tests.common import TransactionCase, tagged, warmup


@tagged("post_install", "-at_install", "base_perf")
class TestBasePerfRegression(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.partners = cls.env["res.partner"].create(
            [
                {"name": f"PerfPartner_{i}", "barcode": f"PERF-BC-{i:04d}"}
                for i in range(10)
            ]
        )

        cls.vat_partners = (
            cls.env["res.partner"]
            .with_context(no_vat_validation=True)
            .create(
                [
                    {
                        "name": f"VATPartner_{i}",
                        "vat": f"BE099900{i:04d}",
                        "country_id": cls.env.ref("base.be").id,
                    }
                    for i in range(5)
                ]
            )
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
        actions = self.window_actions
        self.env.invalidate_all()
        with self.assertQueryCount(2):
            actions._check_path()

    @warmup
    def test_check_barcode_batch(self):
        partners = self.partners
        self.env.invalidate_all()
        with self.assertQueryCount(2):
            partners._check_barcode_unicity()

    @warmup
    def test_compute_show_code_history(self):
        actions = self.server_actions
        self.env.invalidate_all()
        with self.assertQueryCount(9):
            actions._compute_show_code_history()

    @warmup
    def test_get_bindings_cold_cache(self):
        Actions = self.env["ir.actions.actions"]
        self.registry.clear_all_caches()
        self.env.invalidate_all()
        with self.assertQueryCount(10):
            Actions._get_bindings("res.partner")

    @warmup
    def test_compute_partner_share(self):
        partners = self.partners
        self.env.invalidate_all()
        with self.assertQueryCount(4):
            partners._compute_partner_share()

    @warmup
    def test_compute_is_public(self):
        partners = self.partners
        self.env.invalidate_all()
        with self.assertQueryCount(6):
            partners._compute_is_public()

    @warmup
    def test_compute_main_user_id(self):
        partners = self.partners
        self.env.invalidate_all()
        with self.assertQueryCount(5):
            partners._compute_main_user_id()

    @warmup
    def test_compute_same_vat(self):
        partners = self.vat_partners
        self.env.invalidate_all()
        with self.assertQueryCount(10):
            partners._compute_same_identifier_partners()

    @warmup
    def test_selection_target_model_cached(self):
        ServerAction = self.env["ir.actions.server"]
        ServerAction._selection_target_model()
        self.env.invalidate_all()
        with self.assertQueryCount(0):
            ServerAction._selection_target_model()

    @warmup
    def test_ir_model_view_ids(self):
        ir_models = self.env["ir.model"].search([], limit=20)
        self.env.invalidate_all()
        with self.assertQueryCount(4):
            ir_models._compute_view_ids()

    @warmup
    def test_ir_model_inherited_models(self):
        ir_models = self.env["ir.model"].search([], limit=20)
        self.env.invalidate_all()
        with self.assertQueryCount(5):
            ir_models._compute_inherited_model_ids()

    @warmup
    def test_ir_model_compute_count(self):
        ir_models = self.env["ir.model"].search([], limit=20)
        self.env.invalidate_all()
        with self.assertQueryCount(3):
            ir_models.mapped("count")

    def test_create_partners_does_not_fetch_per_record(self):
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
