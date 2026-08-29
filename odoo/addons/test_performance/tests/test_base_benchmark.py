import gc

from odoo.tests.benchmark import BenchmarkCase
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "base_benchmark")
class TestBaseBenchmark(BenchmarkCase, TransactionCase):
    benchmark_log_prefix = "BASE_BENCHMARK"

    def setUp(self):
        super().setUp()
        gc.collect()

    def test_bench_01_check_path(self):
        actions = self.env["ir.actions.act_window"].create(
            [
                {
                    "name": f"BenchWindow_{i}",
                    "res_model": "res.partner",
                    "path": f"bench-path-{i}",
                }
                for i in range(50)
            ]
        )
        self._run_benchmark("check_path (50 actions)", actions._check_path)

    def test_bench_02_check_barcode(self):
        partners = self.env["res.partner"].create(
            [
                {"name": f"BenchBC_{i}", "barcode": f"BENCH-BC-{i:04d}"}
                for i in range(50)
            ]
        )
        self._run_benchmark(
            "check_barcode (50 partners)", partners._check_barcode_unicity
        )

    def test_bench_03_get_bindings(self):
        Actions = self.env["ir.actions.actions"]
        registry = self.registry

        def bench():
            registry.clear_all_caches()
            Actions._get_bindings("res.partner")

        self._run_benchmark("get_bindings cold (res.partner)", bench)

    def test_bench_04_compute_partner_share(self):
        partners = self.env["res.partner"].create(
            [{"name": f"BenchShare_{i}"} for i in range(100)]
        )
        self._run_benchmark(
            "compute_partner_share (100 partners)", partners._compute_partner_share
        )

    def test_bench_05_compute_same_vat(self):
        partners = (
            self.env["res.partner"]
            .with_context(no_vat_validation=True)
            .create(
                [
                    {
                        "name": f"BenchVAT_{i}",
                        "vat": f"BE{i:010d}",
                        "country_id": self.env.ref("base.be").id,
                    }
                    for i in range(20)
                ]
            )
        )
        self._run_benchmark(
            "compute_same_vat (20 partners)",
            partners._compute_same_identifier_partners,
        )

    def test_bench_06_compute_is_public(self):
        partners = self.env["res.partner"].create(
            [{"name": f"BenchPublic_{i}"} for i in range(50)]
        )
        self._run_benchmark(
            "compute_is_public (50 partners)", partners._compute_is_public
        )

    def test_bench_07_compute_main_user_id(self):
        partners = self.env["res.partner"].create(
            [{"name": f"BenchMainUser_{i}"} for i in range(50)]
        )
        self._run_benchmark(
            "compute_main_user_id (50 partners)", partners._compute_main_user_id
        )

    def test_bench_08_selection_target_model(self):
        ServerAction = self.env["ir.actions.server"]
        ServerAction._selection_target_model()
        self._run_benchmark(
            "selection_target_model (warm cache)",
            ServerAction._selection_target_model,
            iterations=50,
            invalidate_cache=False,
        )

    def test_bench_09_company_init(self):
        self._run_benchmark("company_init (paperformat)", self.env["res.company"].init)

    def test_bench_10_ir_model_view_ids(self):
        models = self.env["ir.model"].search([], limit=50)
        self._run_benchmark("ir_model_view_ids (50 models)", models._compute_view_ids)

    def test_bench_11_ir_model_inherited_models(self):
        models = self.env["ir.model"].search([], limit=50)
        self._run_benchmark(
            "ir_model_inherited_models (50 models)", models._compute_inherited_model_ids
        )

    def test_bench_12_ir_model_compute_count(self):
        models = self.env["ir.model"].search([], limit=50)
        self._run_benchmark("ir_model_compute_count (50 models)", models._compute_count)

    def test_bench_13_ir_model_fields_display_name(self):
        ir_fields = self.env["ir.model.fields"].search([], limit=100)
        self._run_benchmark(
            "ir_model_fields_display_name (100 fields)",
            lambda: ir_fields.mapped("display_name"),
        )

    def test_bench_99_summary(self):
        self.log_benchmark_summary()
