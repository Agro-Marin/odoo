import gc
import logging

from odoo.fields import Domain
from odoo.orm.domain.ast import DomainCondition, _optimize_nary_sort_key
from odoo.tests.benchmark import PerfTimer
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import OrderedSet

from ._perf_timer import run_perf_timer

_logger = logging.getLogger(__name__)

N = 2000
WARMUP = 200


def _log_result(timer: PerfTimer, name: str):
    stats = timer.stats(name, warmup=0)
    _logger.info("[DOMAIN_BENCH] %s", stats.get("summary", name))
    return stats


DOMAIN_SINGLE = [("name", "=", "test")]

DOMAIN_SMALL = [
    ("partner_id", "!=", False),
    ("name", "ilike", "bench"),
    ("value", ">", 50),
]

DOMAIN_MEDIUM = [
    "&",
    ("partner_id", "!=", False),
    "|",
    "|",
    "&",
    ("name", "ilike", "bench"),
    ("value", ">", 50),
    "&",
    ("name", "ilike", "test"),
    ("value", "<=", 100),
    "&",
    ("total", "!=", 0),
    ("value", "in", [1, 2, 3, 4, 5]),
]

DOMAIN_LARGE = [
    "|",
    "&",
    "&",
    ("name", "ilike", "a"),
    ("value", ">", 10),
    "&",
    ("total", ">=", 0),
    ("partner_id", "!=", False),
    "&",
    "|",
    "&",
    ("name", "=like", "bench%"),
    ("value", "in", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]),
    "&",
    ("name", "ilike", "test"),
    ("value", "<=", 200),
    "|",
    "&",
    ("name", "=", "exact"),
    ("value", "=", 42),
    "&",
    "|",
    ("total", ">", 0),
    ("total", "=", 0),
    "&",
    ("value", ">=", 0),
    ("value", "<", 1000),
]

DOMAIN_MERGEABLE = [
    ("value", "in", [1, 2, 3]),
    ("value", "in", [3, 4, 5]),
    ("value", "in", [5, 6, 7]),
    ("name", "ilike", "a"),
    ("name", "ilike", "b"),
]

DOMAIN_DUPLICATES = [
    "|",
    "|",
    "|",
    ("name", "=", "a"),
    ("name", "=", "a"),
    ("name", "=", "b"),
    ("name", "=", "b"),
]

DOMAIN_MANY_CHILDREN = ["|"] * 11 + [("value", "=", i) for i in range(12)]

DOMAIN_RELATIONAL = [
    ("partner_id", "any", [("name", "ilike", "test"), ("active", "=", True)]),
]


@tagged("standard", "domain_benchmark")
class TestDomainBenchmark(TransactionCase):
    """Timing only: no test_* method here asserts on a measured value.

    A failure here is an exception, never a performance regression.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Model = cls.env["test_performance.base"]
        cls.all_stats: list[dict] = []

    def setUp(self):
        super().setUp()
        gc.collect()

    def _bench(self, name: str, func, n: int = N, warmup: int = WARMUP) -> dict:
        timer = run_perf_timer(func, n, warmup)
        stats = _log_result(timer, name)
        self.all_stats.append(stats)
        return stats

    def test_01_parse_single(self):
        self._bench("parse: single condition", lambda: Domain(DOMAIN_SINGLE))

    def test_01_parse_small(self):
        self._bench("parse: 3 conditions", lambda: Domain(DOMAIN_SMALL))

    def test_01_parse_medium(self):
        self._bench("parse: 10 conditions (mixed ops)", lambda: Domain(DOMAIN_MEDIUM))

    def test_01_parse_large(self):
        self._bench("parse: 25 conditions (complex)", lambda: Domain(DOMAIN_LARGE))

    def test_01_parse_relational(self):
        self._bench(
            "parse: relational (any subdomain)",
            lambda: Domain(DOMAIN_RELATIONAL),
        )

    def test_02_parse_constructor_3arg(self):
        self._bench("parse: 3-arg constructor", lambda: Domain("name", "=", "test"))

    def test_02_parse_passthrough(self):
        d = Domain(DOMAIN_SMALL)
        self._bench("parse: passthrough (already Domain)", lambda: Domain(d))

    def test_02_parse_true_false(self):
        self._bench("parse: Domain(True)", lambda: Domain(True))

    def test_02_parse_empty_list(self):
        self._bench("parse: Domain([])", lambda: Domain([]))

    def test_10_optimize_single(self):
        d = Domain(DOMAIN_SINGLE)
        model = self.Model
        self._bench("optimize_full: single condition", lambda: d.optimize_full(model))

    def test_10_optimize_small(self):
        d = Domain(DOMAIN_SMALL)
        model = self.Model
        self._bench("optimize_full: 3 conditions", lambda: d.optimize_full(model))

    def test_10_optimize_medium(self):
        d = Domain(DOMAIN_MEDIUM)
        model = self.Model
        self._bench("optimize_full: 10 conditions", lambda: d.optimize_full(model))

    def test_10_optimize_large(self):
        d = Domain(DOMAIN_LARGE)
        model = self.Model
        self._bench("optimize_full: 25 conditions", lambda: d.optimize_full(model))

    def test_11_optimize_mergeable(self):
        d = Domain(DOMAIN_MERGEABLE)
        model = self.Model
        self._bench("optimize_full: mergeable in-sets", lambda: d.optimize_full(model))

    def test_11_optimize_duplicates(self):
        d = Domain(DOMAIN_DUPLICATES)
        model = self.Model
        self._bench("optimize_full: duplicates", lambda: d.optimize_full(model))

    def test_11_optimize_relational(self):
        d = Domain(DOMAIN_RELATIONAL)
        model = self.Model
        self._bench("optimize_full: relational any", lambda: d.optimize_full(model))

    def test_12_optimize_basic_only(self):
        d = Domain(DOMAIN_MEDIUM)
        model = self.Model
        self._bench("optimize (BASIC): 10 conditions", lambda: d.optimize(model))

    def test_20_sort_key_condition(self):
        cond = DomainCondition("name", "=", "test")
        self._bench("sort_key: DomainCondition", lambda: _optimize_nary_sort_key(cond))

    def test_20_sort_key_nary(self):
        d = Domain(DOMAIN_SMALL)
        self._bench("sort_key: DomainAnd", lambda: _optimize_nary_sort_key(d))

    def test_21_sort_children(self):
        # DOMAIN_MANY_CHILDREN is a flat OR of 12 distinct leaves, so
        # `.children` is a genuinely larger/distinct set to sort — not the
        # same 3-4 elements of a smaller domain repeated.
        d = Domain(DOMAIN_MANY_CHILDREN)
        items = list(d.children) if hasattr(d, "children") else [d]
        self._bench(
            "sort: 10+ children by sort_key",
            lambda: sorted(items, key=_optimize_nary_sort_key),
        )

    def test_30_to_sql_single(self):
        d = Domain(DOMAIN_SINGLE).optimize_full(self.Model)
        model = self.Model
        from odoo.tools import Query

        def bench():
            q = Query(model.env, model._table, model._table_sql)
            d._to_sql(model, model._table, q)

        self._bench("to_sql: single condition", bench)

    def test_30_to_sql_medium(self):
        d = Domain(DOMAIN_MEDIUM).optimize_full(self.Model)
        model = self.Model
        from odoo.tools import Query

        def bench():
            q = Query(model.env, model._table, model._table_sql)
            d._to_sql(model, model._table, q)

        self._bench("to_sql: 10 conditions", bench)

    def test_30_to_sql_large(self):
        d = Domain(DOMAIN_LARGE).optimize_full(self.Model)
        model = self.Model
        from odoo.tools import Query

        def bench():
            q = Query(model.env, model._table, model._table_sql)
            d._to_sql(model, model._table, q)

        self._bench("to_sql: 25 conditions", bench)

    def test_40_e2e_single(self):
        model = self.Model
        from odoo.tools import Query

        def bench():
            d = Domain(DOMAIN_SINGLE).optimize_full(model)
            q = Query(model.env, model._table, model._table_sql)
            d._to_sql(model, model._table, q)

        self._bench("e2e: single condition", bench)

    def test_40_e2e_medium(self):
        model = self.Model
        from odoo.tools import Query

        def bench():
            d = Domain(DOMAIN_MEDIUM).optimize_full(model)
            q = Query(model.env, model._table, model._table_sql)
            d._to_sql(model, model._table, q)

        self._bench("e2e: 10 conditions", bench)

    def test_40_e2e_large(self):
        model = self.Model
        from odoo.tools import Query

        def bench():
            d = Domain(DOMAIN_LARGE).optimize_full(model)
            q = Query(model.env, model._table, model._table_sql)
            d._to_sql(model, model._table, q)

        self._bench("e2e: 25 conditions", bench)

    def test_50_domcondition_new(self):
        self._bench(
            "alloc: DomainCondition.__new__",
            lambda: DomainCondition("name", "=", "test"),
        )

    def test_50_domcondition_checked(self):
        self._bench(
            "alloc: DomainCondition + checked()",
            lambda: DomainCondition("name", "=", "test").checked(),
        )

    def test_51_orderedset_creation(self):
        vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        self._bench("alloc: OrderedSet(10 ints)", lambda: OrderedSet(vals))

    def test_51_orderedset_intersection(self):
        a = OrderedSet([1, 2, 3, 4, 5, 6, 7, 8])
        b = OrderedSet([3, 4, 5, 6, 7, 8, 9, 10])
        self._bench("OrderedSet & OrderedSet (8 elems)", lambda: a & b)

    def test_99_summary(self):
        if not self.all_stats:
            return

        _logger.info("\n%s", "=" * 100)
        _logger.info("[DOMAIN_BENCH] SUMMARY — sorted by p50 (descending)")
        _logger.info("=" * 100)
        _logger.info(
            "%-55s %10s %10s %10s %6s",
            "Benchmark",
            "p50 (µs)",
            "p95 (µs)",
            "mean (µs)",
            "CV",
        )
        _logger.info("-" * 100)

        by_p50 = sorted(self.all_stats, key=lambda s: s.get("p50_us", 0), reverse=True)
        for s in by_p50:
            _logger.info(
                "%-55s %10.1f %10.1f %10.1f %6.2f",
                s.get("name", "?")[:55],
                s.get("p50_us", 0),
                s.get("p95_us", 0),
                s.get("mean_us", 0),
                s.get("cv", 0),
            )

        phases = {
            "Parsing": [
                s for s in self.all_stats if s.get("name", "").startswith("parse:")
            ],
            "Optimization": [
                s for s in self.all_stats if "optimize" in s.get("name", "")
            ],
            "SQL Generation": [
                s for s in self.all_stats if s.get("name", "").startswith("to_sql:")
            ],
            "End-to-End": [
                s for s in self.all_stats if s.get("name", "").startswith("e2e:")
            ],
            "Allocation": [
                s
                for s in self.all_stats
                if s.get("name", "").startswith(("alloc:", "OrderedSet"))
            ],
        }
        _logger.info("\n%s", "-" * 100)
        _logger.info("[DOMAIN_BENCH] PHASE BREAKDOWN (mean p50):")
        for phase, stats in phases.items():
            if stats:
                avg_p50 = sum(s.get("p50_us", 0) for s in stats) / len(stats)
                max_p50 = max(s.get("p50_us", 0) for s in stats)
                _logger.info(
                    "  %-20s  avg p50=%8.1f µs  max p50=%8.1f µs  (%d tests)",
                    phase,
                    avg_p50,
                    max_p50,
                    len(stats),
                )

        _logger.info("=" * 100)
