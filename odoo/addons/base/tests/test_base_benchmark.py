import gc
import logging

from odoo.tests.benchmark import BenchmarkStats, run_benchmark
from odoo.tests.common import TransactionCase, tagged

_logger = logging.getLogger(__name__)

DEFAULT_ITERATIONS = 30
WARMUP_ITERATIONS = 5


@tagged("post_install", "-at_install", "base_benchmark")
class TestBaseBenchmark(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.all_results: list[BenchmarkStats] = []

    def setUp(self):
        super().setUp()
        gc.collect()

    def _run_benchmark(
        self,
        name: str,
        func,
        *,
        iterations: int = DEFAULT_ITERATIONS,
        warmup: int = WARMUP_ITERATIONS,
        setup=None,
        invalidate_cache: bool = True,
    ) -> BenchmarkStats:
        stats = run_benchmark(
            name,
            func,
            iterations=iterations,
            warmup=warmup,
            setup=setup,
            invalidate=self.env.invalidate_all if invalidate_cache else None,
        )
        self.all_results.append(stats)
        _logger.info("[BASE_BENCHMARK] %s", stats.summary())
        return stats

    def test_bench_check_path(self):
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

        self._run_benchmark(
            "check_path (50 actions)",
            actions._check_path,
        )

    def test_bench_check_barcode(self):
        partners = self.env["res.partner"].create(
            [
                {"name": f"BenchBC_{i}", "barcode": f"BENCH-BC-{i:04d}"}
                for i in range(50)
            ]
        )

        self._run_benchmark(
            "check_barcode (50 partners)",
            partners._check_barcode_unicity,
        )

    def test_bench_get_bindings(self):
        Actions = self.env["ir.actions.actions"]
        registry = self.registry

        def bench():
            registry.clear_all_caches()
            Actions._get_bindings("res.partner")

        self._run_benchmark(
            "get_bindings cold (res.partner)",
            bench,
            invalidate_cache=True,
        )

    def test_bench_compute_partner_share(self):
        partners = self.env["res.partner"].create(
            [{"name": f"BenchShare_{i}"} for i in range(100)]
        )

        self._run_benchmark(
            "compute_partner_share (100 partners)",
            partners._compute_partner_share,
        )

    def test_bench_compute_same_vat(self):
        # The benchmark needs distinct VAT strings, not checksum-valid ones. Without
        # no_vat_validation these synthetic numbers fail base_vat's Belgian check,
        # making a core benchmark depend on whether an optional addon is installed.
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
            partners._compute_same_vat_partner_id,
        )

    def test_bench_compute_is_public(self):
        partners = self.env["res.partner"].create(
            [{"name": f"BenchPublic_{i}"} for i in range(50)]
        )

        self._run_benchmark(
            "compute_is_public (50 partners)",
            partners._compute_is_public,
        )

    def test_bench_compute_main_user_id(self):
        partners = self.env["res.partner"].create(
            [{"name": f"BenchMainUser_{i}"} for i in range(50)]
        )

        self._run_benchmark(
            "compute_main_user_id (50 partners)",
            partners._compute_main_user_id,
        )

    def test_bench_selection_target_model(self):
        ServerAction = self.env["ir.actions.server"]
        ServerAction._selection_target_model()

        self._run_benchmark(
            "selection_target_model (warm cache)",
            ServerAction._selection_target_model,
            iterations=50,
            invalidate_cache=False,
        )

    def test_bench_company_init(self):
        Company = self.env["res.company"]

        self._run_benchmark(
            "company_init (paperformat)",
            Company.init,
        )

    def test_bench_ir_model_view_ids(self):
        models = self.env["ir.model"].search([], limit=50)

        self._run_benchmark(
            "ir_model_view_ids (50 models)",
            models._compute_view_ids,
        )

    def test_bench_ir_model_inherited_models(self):
        models = self.env["ir.model"].search([], limit=50)

        self._run_benchmark(
            "ir_model_inherited_models (50 models)",
            models._compute_inherited_model_ids,
        )

    def test_bench_ir_model_compute_count(self):
        models = self.env["ir.model"].search([], limit=50)

        self._run_benchmark(
            "ir_model_compute_count (50 models)",
            models._compute_count,
        )

    def test_bench_ir_model_fields_display_name(self):
        ir_fields = self.env["ir.model.fields"].search([], limit=100)

        def bench():
            ir_fields.mapped("display_name")

        self._run_benchmark(
            "ir_model_fields_display_name (100 fields)",
            bench,
        )
