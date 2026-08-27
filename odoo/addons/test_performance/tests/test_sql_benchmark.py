import gc
import json
import logging
import statistics
import time
from datetime import datetime

from odoo.tests.benchmark import (
    OUTLIER_PERCENTILE,
    BenchmarkCase,
)
from odoo.tests.common import TransactionCase, tagged

_logger = logging.getLogger(__name__)

DEFAULT_ITERATIONS = 50
WARMUP_ITERATIONS = 5


@tagged("-standard", "sql_benchmark")
class TestSQLBenchmark(BenchmarkCase, TransactionCase):
    """Timing only: no test_* method here asserts on a measured value.

    A failure here is an exception, never a performance regression — see
    BenchmarkCase's own docstring (odoo/tests/benchmark.py).
    """

    benchmark_log_prefix = "SQL_BENCHMARK"
    benchmark_iterations = DEFAULT_ITERATIONS
    benchmark_warmup = WARMUP_ITERATIONS

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]
        cls.User = cls.env["res.users"]
        cls.Country = cls.env["res.country"]

        cls._create_test_data()

    @classmethod
    def _create_test_data(cls):
        existing = cls.Partner.search_count([("name", "like", "BenchmarkPartner%")])
        if existing < 100:
            _logger.info("[SQL_BENCHMARK] Creating test data...")
            partners_data = [
                {
                    "name": f"BenchmarkPartner_{i}",
                    "email": f"benchmark{i}@test.com",
                    "phone": f"+1555{i:04d}",
                    "is_company": i % 3 == 0,
                    "country_id": (
                        cls.env.ref("base.mx").id
                        if i % 2 == 0
                        else cls.env.ref("base.us").id
                    ),
                }
                for i in range(100)
            ]
            cls.Partner.create(partners_data)
            _logger.info("[SQL_BENCHMARK] Test data created.")

    def setUp(self):
        super().setUp()
        gc.collect()
        self.Partner.search_count([])

    def test_01_single_record_read_by_id(self):
        partner = self.Partner.search([], limit=1)

        def bench():
            self.Partner.browse(partner.id).read(
                ["name", "email", "phone", "country_id"]
            )

        self._run_benchmark("Single Record Read (by ID)", bench)

    def test_02_single_record_create(self):
        counter = [0]

        def bench():
            counter[0] += 1
            self.Partner.create(
                {
                    "name": f"BenchCreate_{counter[0]}_{time.time()}",
                    "email": "bench@test.com",
                }
            )

        self._run_benchmark("Single Record Create", bench, iterations=30)

    def test_03_single_record_write(self):
        partner = self.Partner.create({"name": "WriteTest"})

        def bench():
            partner.write({"name": f"Updated_{time.time()}"})

        self._run_benchmark("Single Record Write", bench)

    def test_04_single_record_unlink(self):

        def setup():
            self._partner_to_delete = self.Partner.create({"name": "ToDelete"})

        def bench():
            self._partner_to_delete.unlink()

        self._run_benchmark("Single Record Unlink", bench, setup=setup, iterations=30)

    def test_10_search_simple_domain(self):

        def bench():
            self.Partner.search([("is_company", "=", True)], limit=50)

        self._run_benchmark("Search Simple Domain (limit=50)", bench)

    def test_11_search_complex_domain(self):

        def bench():
            self.Partner.search(
                [
                    ("is_company", "=", True),
                    "|",
                    ("country_id.code", "=", "MX"),
                    ("country_id.code", "=", "US"),
                    ("email", "!=", False),
                ],
                limit=100,
            )

        self._run_benchmark("Search Complex Domain (limit=100)", bench)

    def test_12_search_with_order(self):

        def bench():
            self.Partner.search(
                [("is_company", "=", True)], order="name desc, id", limit=100
            )

        self._run_benchmark("Search with ORDER BY (limit=100)", bench)

    def test_13_search_count(self):

        def bench():
            self.Partner.search_count([("is_company", "=", True)])

        self._run_benchmark("Search Count", bench)

    def test_14_search_read_combined(self):

        def bench():
            self.Partner.search_read(
                [("is_company", "=", True)],
                fields=["name", "email", "phone", "country_id"],
                limit=50,
            )

        self._run_benchmark("Search Read Combined (limit=50)", bench)

    def test_20_batch_create_10(self):
        counter = [0]

        def bench():
            counter[0] += 1
            self.Partner.create(
                [
                    {
                        "name": f"Batch10_{counter[0]}_{i}",
                        "email": f"b{i}@test.com",
                    }
                    for i in range(10)
                ]
            )

        self._run_benchmark("Batch Create (10 records)", bench, iterations=20)

    def test_21_batch_create_100(self):
        counter = [0]

        def bench():
            counter[0] += 1
            self.Partner.create(
                [
                    {
                        "name": f"Batch100_{counter[0]}_{i}",
                        "email": f"b{i}@test.com",
                    }
                    for i in range(100)
                ]
            )

        self._run_benchmark("Batch Create (100 records)", bench, iterations=10)

    def test_22_batch_write(self):
        partners = self.Partner.search(
            [("name", "like", "BenchmarkPartner%")], limit=50
        )

        def bench():
            partners.write({"phone": f"+1555{int(time.time()) % 10000:04d}"})

        self._run_benchmark("Batch Write (50 records)", bench)

    def test_23_batch_read(self):
        partners = self.Partner.search([], limit=100)

        def bench():
            partners.read(["name", "email", "phone", "country_id", "is_company"])

        self._run_benchmark("Batch Read (100 records, 5 fields)", bench)

    def test_30_relational_many2one_access(self):
        partners = self.Partner.search([("country_id", "!=", False)], limit=50)

        def bench():
            for p in partners:
                _ = p.country_id.name
                _ = p.country_id.code

        self._run_benchmark("Many2one Access (50 records)", bench)

    def test_31_relational_one2many_access(self):
        countries = self.Country.search([], limit=10)

        def bench():
            for c in countries:
                _ = len(c.state_ids)
                for state in c.state_ids[:5]:
                    _ = state.name

        self._run_benchmark("One2many Access (10 countries)", bench)

    def test_32_relational_deep_traversal(self):
        partners = self.Partner.search([("country_id", "!=", False)], limit=20)

        def bench():
            for p in partners:
                _ = p.country_id.currency_id.name if p.country_id.currency_id else None

        self._run_benchmark("Deep Relational Traversal (3 levels)", bench)

    def test_40_computed_field_access(self):
        partners = self.Partner.search([], limit=100)

        def bench():
            for p in partners:
                _ = p.display_name

        self._run_benchmark("Computed Field Access (100 records)", bench)

    def test_41_computed_field_with_depends(self):
        users = self.User.search([], limit=20)

        def bench():
            for u in users:
                _ = u.display_name
                _ = u.partner_id.display_name

        self._run_benchmark("Computed Fields with Dependencies (20 users)", bench)

    def test_50_raw_sql_select(self):

        def bench():
            self.env.cr.execute("""
                SELECT id, name, email, phone
                FROM res_partner
                WHERE is_company = true
                LIMIT 100
            """)
            self.env.cr.fetchall()

        self._run_benchmark("Raw SQL SELECT (100 rows)", bench)

    def test_51_orm_equivalent_select(self):

        def bench():
            self.Partner.search_read(
                [("is_company", "=", True)],
                fields=["name", "email", "phone"],
                limit=100,
            )

        self._run_benchmark("ORM Equivalent SELECT (100 rows)", bench)

    def test_52_raw_sql_insert(self):
        counter = [0]

        def bench():
            counter[0] += 1
            self.env.cr.execute(
                """
                INSERT INTO res_partner (name, email, active, create_uid, write_uid, create_date, write_date)
                VALUES (%s, %s, true, %s, %s, NOW(), NOW())
            """,
                (
                    f"RawSQL_{counter[0]}",
                    "raw@test.com",
                    self.env.uid,
                    self.env.uid,
                ),
            )

        self._run_benchmark("Raw SQL INSERT", bench, iterations=30)

    def test_60_savepoint_overhead(self):

        def bench():
            with self.env.cr.savepoint():
                self.Partner.search_count([])

        self._run_benchmark("Savepoint Overhead", bench)

    def test_61_multiple_queries_single_transaction(self):

        def bench():
            self.Partner.search_count([("is_company", "=", True)])
            self.Partner.search_count([("is_company", "=", False)])
            self.Partner.search([("country_id", "!=", False)], limit=10)
            self.Country.search_count([])

        self._run_benchmark("Multiple Queries (4 queries, 1 transaction)", bench)

    def test_70_cache_hit_single(self):
        partner = self.Partner.search([], limit=1)
        _ = partner.name

        def bench():
            _ = partner.name

        # invalidate_cache defaults to True, which would wipe the cache
        # before every timed iteration -- exactly the opposite of what a
        # "cache hit" benchmark needs.
        self._run_benchmark(
            "Cache Hit (single field)", bench, iterations=100, invalidate_cache=False
        )

    def test_71_cache_miss_single(self):
        partner = self.Partner.search([], limit=1)

        def bench():
            _ = partner.name

        # invalidate_cache defaults to True, so the harness already
        # invalidates the cache before every iteration; no extra setup()
        # is needed to force a miss.
        self._run_benchmark("Cache Miss (single field)", bench)

    def test_72_prefetch_behavior(self):
        partners = self.Partner.search([], limit=100)

        def bench():
            for p in partners:
                _ = p.name

        # invalidate_cache defaults to True, so the harness already
        # invalidates before every iteration (including the first): the
        # explicit invalidate_all() this test used to do beforehand was
        # redundant with it, and this benchmark genuinely wants the cache
        # cold on every iteration to measure the prefetch-trigger cost
        # repeatedly, unlike test_70's "Cache Hit".
        self._run_benchmark("Prefetch (100 records)", bench)

    def test_80_sequential_operations(self):

        def bench():
            self.Partner.search_count([("is_company", "=", True)])
            self.Partner.search_count([("is_company", "=", False)])
            self.Country.search_count([])
            self.User.search_count([])

        self._run_benchmark("Sequential Operations (4 counts)", bench)

    def test_85_scaling_batch_create_1(self):
        counter = [0]

        def bench():
            counter[0] += 1
            self.Partner.create(
                {"name": f"Scale1_{counter[0]}", "email": "scale@test.com"}
            )

        self._run_benchmark("Scale: Create 1 record", bench, iterations=30)

    def test_85_scaling_batch_create_5(self):
        counter = [0]

        def bench():
            counter[0] += 1
            self.Partner.create(
                [
                    {
                        "name": f"Scale5_{counter[0]}_{i}",
                        "email": f"s{i}@test.com",
                    }
                    for i in range(5)
                ]
            )

        self._run_benchmark("Scale: Create 5 records", bench, iterations=30)

    def test_85_scaling_batch_create_25(self):
        counter = [0]

        def bench():
            counter[0] += 1
            self.Partner.create(
                [
                    {
                        "name": f"Scale25_{counter[0]}_{i}",
                        "email": f"s{i}@test.com",
                    }
                    for i in range(25)
                ]
            )

        self._run_benchmark("Scale: Create 25 records", bench, iterations=20)

    def test_85_scaling_batch_create_50(self):
        counter = [0]

        def bench():
            counter[0] += 1
            self.Partner.create(
                [
                    {
                        "name": f"Scale50_{counter[0]}_{i}",
                        "email": f"s{i}@test.com",
                    }
                    for i in range(50)
                ]
            )

        self._run_benchmark("Scale: Create 50 records", bench, iterations=15)

    def test_86_scaling_search_10(self):

        def bench():
            self.Partner.search([], limit=10)

        self._run_benchmark("Scale: Search limit=10", bench)

    def test_86_scaling_search_50(self):

        def bench():
            self.Partner.search([], limit=50)

        self._run_benchmark("Scale: Search limit=50", bench)

    def test_86_scaling_search_200(self):

        def bench():
            self.Partner.search([], limit=200)

        self._run_benchmark("Scale: Search limit=200", bench)

    def test_86_scaling_search_500(self):

        def bench():
            self.Partner.search([], limit=500)

        self._run_benchmark("Scale: Search limit=500", bench)

    def test_90_independent_reads_2_tables(self):

        def bench():
            self.Partner.search_read([("is_company", "=", True)], limit=50)
            self.Country.search_read([], limit=50)

        self._run_benchmark("Independent: 2 table reads", bench)

    def test_90_independent_reads_4_tables(self):

        def bench():
            self.Partner.search_read([("is_company", "=", True)], limit=30)
            self.Country.search_read([], limit=30)
            self.User.search_read([], fields=["name", "login"], limit=30)
            self.env["res.currency"].search_read([], limit=30)

        self._run_benchmark("Independent: 4 table reads", bench)

    def test_91_dependent_chain(self):

        def bench():
            partner = self.Partner.search([("country_id", "!=", False)], limit=1)
            if partner:
                country = partner.country_id
                currency = country.currency_id
                if currency:
                    _ = currency.rate

        self._run_benchmark("Dependent: Query chain", bench)

    def test_92_mixed_independent_dependent(self):

        def bench():
            companies = self.Partner.search([("is_company", "=", True)], limit=20)
            self.Country.search([], limit=20)

            for company in companies[:5]:
                _ = company.country_id.name

        self._run_benchmark("Mixed: Independent + Dependent", bench)

    def test_93_n_plus_one_pattern(self):
        partners = self.Partner.search([("country_id", "!=", False)], limit=20)
        self.env.invalidate_all()

        def bench():
            return [
                {
                    "name": p.name,
                    "country": p.country_id.name,
                    "currency": (
                        p.country_id.currency_id.name
                        if p.country_id.currency_id
                        else None
                    ),
                }
                for p in partners
            ]

        self._run_benchmark("N+1 Pattern (20 records, 3 levels)", bench)

    def test_94_bulk_field_access(self):
        partners = self.Partner.search([], limit=100)
        self.env.invalidate_all()

        def bench():
            names = partners.mapped("name")
            emails = partners.mapped("email")
            phones = partners.mapped("phone")
            return names, emails, phones

        self._run_benchmark("Bulk mapped() access (100 records, 3 fields)", bench)

    def test_95_simple_where(self):

        def bench():
            self.Partner.search([("active", "=", True)], limit=100)

        self._run_benchmark("Query: Simple WHERE", bench)

    def test_95_multiple_conditions(self):

        def bench():
            self.Partner.search(
                [
                    ("active", "=", True),
                    ("is_company", "=", True),
                    ("email", "!=", False),
                ],
                limit=100,
            )

        self._run_benchmark("Query: Multiple AND conditions", bench)

    def test_95_or_conditions(self):

        def bench():
            self.Partner.search(
                [
                    "|",
                    "|",
                    ("name", "ilike", "bench"),
                    ("email", "ilike", "bench"),
                    ("phone", "ilike", "555"),
                ],
                limit=100,
            )

        self._run_benchmark("Query: OR conditions", bench)

    def test_95_join_condition(self):

        def bench():
            self.Partner.search(
                [
                    ("country_id.code", "in", ["MX", "US", "CA"]),
                ],
                limit=100,
            )

        self._run_benchmark("Query: JOIN condition", bench)

    def test_96_aggregation_group_by(self):

        def bench():
            self.Partner._read_group(
                domain=[("active", "=", True)],
                groupby=["country_id"],
                aggregates=["__count"],
            )

        self._run_benchmark("Query: GROUP BY aggregation", bench)

    def test_99_generate_summary(self):
        if not self.all_results:
            _logger.info("[SQL_BENCHMARK] No results to summarize.")
            return

        _logger.info("\n%s", "=" * 80)
        _logger.info("[SQL_BENCHMARK] FINAL SUMMARY")
        _logger.info("=" * 80)

        sorted_by_db_ratio = sorted(
            self.all_results, key=lambda x: x.db_ratio, reverse=True
        )

        _logger.info("\n[SQL_BENCHMARK] TOP CANDIDATES FOR ASYNC (by DB wait %%):")
        _logger.info("-" * 70)
        _logger.info("%-45s %8s %8s %8s", "Test Name", "Mean(ms)", "DB%", "Queries")
        _logger.info("-" * 70)
        for stat in sorted_by_db_ratio[:10]:
            _logger.info(
                "%-45s %8.3f %7.1f%% %8.1f",
                stat.name[:45],
                stat.mean_ms,
                stat.db_ratio * 100,
                stat.query_count_mean,
            )

        sorted_by_time = sorted(self.all_results, key=lambda x: x.mean_ms, reverse=True)

        _logger.info("\n[SQL_BENCHMARK] SLOWEST OPERATIONS:")
        _logger.info("-" * 70)
        _logger.info("%-45s %8s %8s %8s", "Test Name", "Mean(ms)", "P95(ms)", "StdDev")
        _logger.info("-" * 70)
        for stat in sorted_by_time[:10]:
            _logger.info(
                "%-45s %8.3f %8.3f %8.3f",
                stat.name[:45],
                stat.mean_ms,
                stat.p95_ms,
                stat.std_dev_ms,
            )

        sorted_by_cv = sorted(self.all_results, key=lambda x: x.cv, reverse=True)

        _logger.info("\n[SQL_BENCHMARK] MOST VARIABLE OPERATIONS (inconsistent):")
        _logger.info("-" * 70)
        _logger.info("%-45s %8s %8s %8s", "Test Name", "CV", "Min(ms)", "Max(ms)")
        _logger.info("-" * 70)
        for stat in sorted_by_cv[:5]:
            _logger.info(
                "%-45s %8.3f %8.3f %8.3f",
                stat.name[:45],
                stat.cv,
                stat.min_ms,
                stat.max_ms,
            )

        export_data = {
            "timestamp": datetime.now().isoformat(),
            "config": {
                "iterations": DEFAULT_ITERATIONS,
                "warmup": WARMUP_ITERATIONS,
                "outlier_percentile": OUTLIER_PERCENTILE,
            },
            "results": [stat.to_dict() for stat in self.all_results],
            "summary": {
                "total_tests": len(self.all_results),
                "avg_db_ratio": statistics.mean(s.db_ratio for s in self.all_results),
                "avg_query_count": statistics.mean(
                    s.query_count_mean for s in self.all_results
                ),
            },
        }

        _logger.info("\n[SQL_BENCHMARK] JSON Export:")
        _logger.info(json.dumps(export_data, indent=2, default=str))

        _logger.info("\n%s", "=" * 80)
        _logger.info("[SQL_BENCHMARK] ASYNC BENEFIT ANALYSIS")
        _logger.info("=" * 80)

        high_db_ratio = [s for s in self.all_results if s.db_ratio > 0.6]
        medium_db_ratio = [s for s in self.all_results if 0.3 <= s.db_ratio <= 0.6]
        low_db_ratio = [s for s in self.all_results if s.db_ratio < 0.3]

        _logger.info("\n1. DB WAIT TIME DISTRIBUTION:")
        _logger.info(
            "   High DB wait (>60%%):    %d operations (%.1f%%)",
            len(high_db_ratio),
            (
                len(high_db_ratio) / len(self.all_results) * 100
                if self.all_results
                else 0
            ),
        )
        _logger.info(
            "   Medium DB wait (30-60%%): %d operations (%.1f%%)",
            len(medium_db_ratio),
            (
                len(medium_db_ratio) / len(self.all_results) * 100
                if self.all_results
                else 0
            ),
        )
        _logger.info(
            "   Low DB wait (<30%%):     %d operations (%.1f%%)",
            len(low_db_ratio),
            (
                len(low_db_ratio) / len(self.all_results) * 100
                if self.all_results
                else 0
            ),
        )

        if high_db_ratio:
            avg_db_time = statistics.mean(s.db_time_ms for s in high_db_ratio)
            total_db_wait = sum(s.db_time_ms for s in high_db_ratio)
            _logger.info("\n   High-ratio operations stats:")
            _logger.info("   - Average DB wait: %.3f ms", avg_db_time)
            _logger.info("   - Total DB wait:   %.3f ms", total_db_wait)

        _logger.info("\n2. INDEPENDENT OPERATIONS ANALYSIS:")
        independent_tests = [s for s in self.all_results if "Independent" in s.name]
        if independent_tests:
            for test in independent_tests:
                estimated_parallel_time = (
                    test.db_time_ms / test.query_count_mean
                    if test.query_count_mean > 0
                    else test.mean_ms
                )
                speedup = (
                    test.mean_ms / estimated_parallel_time
                    if estimated_parallel_time > 0
                    else 1
                )
                _logger.info("   %s:", test.name)
                _logger.info(
                    "      Current (sync):  %.3f ms (%d queries)",
                    test.mean_ms,
                    int(test.query_count_mean),
                )
                _logger.info(
                    "      Theoretical async speedup: %.2fx",
                    min(speedup, test.query_count_mean),
                )

        _logger.info("\n3. SCALING ANALYSIS:")
        scale_create_tests = [
            s for s in self.all_results if s.name.startswith("Scale: Create")
        ]
        scale_search_tests = [
            s for s in self.all_results if s.name.startswith("Scale: Search")
        ]

        if scale_create_tests:
            _logger.info("   Batch Create scaling:")
            for test in sorted(scale_create_tests, key=lambda x: x.mean_ms):
                _logger.info(
                    "      %s: %.3f ms (%.3f ms/record avg)",
                    test.name,
                    test.mean_ms,
                    test.mean_ms / max(1, test.query_count_mean),
                )

        if scale_search_tests:
            _logger.info("   Search scaling:")
            for test in sorted(scale_search_tests, key=lambda x: x.mean_ms):
                _logger.info("      %s: %.3f ms", test.name, test.mean_ms)

        _logger.info("\n4. QUERY COMPLEXITY IMPACT:")
        query_tests = [s for s in self.all_results if s.name.startswith("Query:")]
        if query_tests:
            baseline = next((t for t in query_tests if "Simple WHERE" in t.name), None)
            if baseline:
                _logger.info("   Baseline (Simple WHERE): %.3f ms", baseline.mean_ms)
                for test in query_tests:
                    if test != baseline:
                        overhead = (
                            ((test.mean_ms - baseline.mean_ms) / baseline.mean_ms * 100)
                            if baseline.mean_ms > 0
                            else 0
                        )
                        _logger.info(
                            "   %s: %.3f ms (%+.1f%% vs baseline)",
                            test.name,
                            test.mean_ms,
                            overhead,
                        )

        _logger.info("\n5. THEORETICAL ASYNC BENEFITS:")
        total_sync_time = sum(s.mean_ms for s in self.all_results)
        total_db_time = sum(s.db_time_ms for s in self.all_results)
        total_python_time = sum(s.python_time_ms for s in self.all_results)

        _logger.info("   Total benchmark time (sync): %.3f ms", total_sync_time)
        _logger.info(
            "   Total DB wait time:          %.3f ms (%.1f%%)",
            total_db_time,
            total_db_time / total_sync_time * 100 if total_sync_time > 0 else 0,
        )
        _logger.info(
            "   Total Python time:           %.3f ms (%.1f%%)",
            total_python_time,
            (total_python_time / total_sync_time * 100 if total_sync_time > 0 else 0),
        )

        potential_savings = total_db_time * 0.5
        _logger.info(
            "\n   POTENTIAL ASYNC SAVINGS (conservative 50%% parallelization):"
        )
        _logger.info("   - Estimated time saved: %.3f ms", potential_savings)
        _logger.info(
            "   - Potential speedup:    %.1f%%",
            (potential_savings / total_sync_time * 100 if total_sync_time > 0 else 0),
        )

        _logger.info("\n6. RECOMMENDATIONS:")
        if high_db_ratio:
            _logger.info(
                "   - %d operations spend >60%% time waiting for DB",
                len(high_db_ratio),
            )
            _logger.info("     These are prime candidates for async optimization")
        if independent_tests:
            _logger.info(
                "   - Independent multi-table reads could benefit from parallel execution"
            )
        _logger.info("   - Consider psycopg3 migration for hybrid sync/async support")

        _logger.info("\n%s", "=" * 80)
        _logger.info("[SQL_BENCHMARK] Benchmark complete.")
        _logger.info("=" * 80)
