import base64
import gc
import json
import logging
from collections import deque
from datetime import date, datetime

from odoo.orm.domain import Domain
from odoo.tests.benchmark import PerfTimer
from odoo.tests.common import TransactionCase, tagged

_logger = logging.getLogger(__name__)

ITERATIONS = 200
WARMUP = 10
BATCH_SIZES = (1, 10, 100)


def _bench(func, n=ITERATIONS, warmup=WARMUP):
    timer = PerfTimer()
    for _ in range(warmup):
        func()
    for _ in range(n):
        timer.start()
        func()
        timer.stop()
    return timer


def _log_result(stats: dict):
    _logger.info("[ORM_PERF] %s", stats.get("summary", stats.get("name", "?")))


# Populated by PerfTestCase.setUpClass, keyed by class name, so
# TestFullPipeline's aggregate report can read every suite's results
# without hardcoding each sibling class by name.
_RESULTS_REGISTRY: dict[str, list[dict]] = {}


class PerfTestCase(TransactionCase):
    """Shared base factoring out what all the suites below duplicated.

    setUp's gc.collect(), the _log helper, and test_99_summary (sort
    self.results by p50_us, log) used to be repeated near-verbatim in
    every one of the TestCase classes in this file. summary_title/
    summary_sort/summary_limit capture the handful of ways their
    test_99_summary actually differed; a subclass with a genuinely
    different report (TestAccelClone's two-bucket grouping,
    TestFullPipeline's aggregate section) overrides test_99_summary
    normally instead of forcing a flag through this one.

    odoo.tests.loader.get_module_test_cases only collects test_* methods
    from a class's own __dict__ unless allow_inherited_tests_method is
    set, precisely to let a shared base contribute a test method without
    every subclass needing to redeclare it.
    """

    allow_inherited_tests_method = True

    summary_title = "SUMMARY"
    summary_sort = True
    summary_limit: int | None = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.results: list[dict] = []
        _RESULTS_REGISTRY[cls.__name__] = cls.results

    def setUp(self):
        super().setUp()
        gc.collect()

    def _log(self, stats):
        _log_result(stats)
        self.results.append(stats)

    def test_99_summary(self):
        if not self.results:
            return
        _logger.info("\n[ORM_PERF] === %s ===", self.summary_title)
        results = self.results
        if self.summary_sort:
            results = sorted(results, key=lambda r: r.get("p50_us", 0), reverse=True)
        if self.summary_limit:
            results = results[: self.summary_limit]
        for r in results:
            _logger.info("[ORM_PERF]   %s", r.get("summary", ""))


@tagged("-standard", "orm_perf")
class TestFieldConversion(PerfTestCase):
    summary_title = "FIELD CONVERSION SUMMARY"
    summary_limit = 20

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Model = cls.env["test_performance.all_types"]
        cls.record = cls.Model.create({"name": "bench_convert"})
        cls.partner = cls.env["res.partner"].search([], limit=1)

    def _bench_convert(self, field_name, value, name=None):
        field = self.Model._fields[field_name]
        record = self.record
        label = name or f"convert_to_cache({field.type}:{field_name})"

        timer = _bench(lambda: field.convert_to_cache(value, record))
        stats = timer.stats(label, warmup=0)
        _log_result(stats)
        self.results.append(stats)
        return stats

    def test_01_boolean(self):
        self._bench_convert("f_boolean", True)
        self._bench_convert("f_boolean", 1, "convert_to_cache(boolean:from_int)")
        self._bench_convert("f_boolean", False)

    def test_02_integer(self):
        self._bench_convert("f_integer", 42)
        self._bench_convert("f_integer", 0)
        self._bench_convert("f_integer", None, "convert_to_cache(integer:None)")

    def test_03_float(self):
        self._bench_convert("f_float", 3.14159)
        self._bench_convert("f_float", 0.0)

    def test_04_monetary(self):
        self._bench_convert("f_monetary", 99.99)

    def test_05_char(self):
        self._bench_convert("f_char", "hello world")
        self._bench_convert("f_char", "x" * 255, "convert_to_cache(char:255)")
        self._bench_convert("f_char", None, "convert_to_cache(char:None)")
        self._bench_convert("f_char", False, "convert_to_cache(char:False)")

    def test_06_text(self):
        self._bench_convert("f_text", "Short text.")
        self._bench_convert("f_text", "x" * 10000, "convert_to_cache(text:10k)")

    def test_07_date(self):
        self._bench_convert("f_date", "2025-06-15")
        self._bench_convert("f_date", date(2025, 6, 15), "convert_to_cache(date:obj)")
        self._bench_convert("f_date", False, "convert_to_cache(date:False)")

    def test_08_datetime(self):
        self._bench_convert("f_datetime", "2025-06-15 10:30:00")
        self._bench_convert(
            "f_datetime",
            datetime(2025, 6, 15, 10, 30),
            "convert_to_cache(datetime:obj)",
        )
        self._bench_convert("f_datetime", False, "convert_to_cache(datetime:False)")

    def test_09_selection(self):
        self._bench_convert("f_selection", "draft")
        self._bench_convert("f_selection", "cancel")
        self._bench_convert("f_selection", False, "convert_to_cache(selection:False)")

    def test_10_many2one_int(self):
        self._bench_convert(
            "f_many2one", self.partner.id, "convert_to_cache(many2one:int)"
        )

    def test_10_many2one_record(self):
        self._bench_convert(
            "f_many2one", self.partner, "convert_to_cache(many2one:record)"
        )

    def test_10_many2one_tuple(self):
        self._bench_convert(
            "f_many2one",
            (self.partner.id, "Name"),
            "convert_to_cache(many2one:tuple)",
        )

    def test_10_many2one_none(self):
        self._bench_convert("f_many2one", None, "convert_to_cache(many2one:None)")

    def test_11_json(self):
        small = {"key": "value", "num": 42}
        self._bench_convert("f_json", small, "convert_to_cache(json:small)")
        large = {"k" + str(i): list(range(10)) for i in range(50)}
        self._bench_convert("f_json", large, "convert_to_cache(json:large)")
        self._bench_convert("f_json", None, "convert_to_cache(json:None)")

    def test_12_binary(self):
        small_b64 = base64.b64encode(b"hello world").decode()
        self._bench_convert("f_binary", small_b64, "convert_to_cache(binary:small)")

    def test_13_html(self):
        html = "<p>Hello <b>world</b></p>"
        self._bench_convert("f_html", html, "convert_to_cache(html:small)")

    def test_90_convert_to_record(self):
        record = self.record
        for fname, cache_val, label in [
            ("f_integer", 42, "convert_to_record(integer)"),
            ("f_char", "hello", "convert_to_record(char)"),
            ("f_boolean", True, "convert_to_record(boolean)"),
            ("f_date", date(2025, 6, 15), "convert_to_record(date)"),
            ("f_many2one", self.partner.id, "convert_to_record(many2one)"),
        ]:
            field = self.Model._fields[fname]
            timer = _bench(lambda f=field, v=cache_val: f.convert_to_record(v, record))
            stats = timer.stats(label, warmup=0)
            _log_result(stats)
            self.results.append(stats)

    def test_91_convert_to_read(self):
        record = self.record
        for fname, cache_val, label in [
            ("f_integer", 42, "convert_to_read(integer)"),
            ("f_char", "hello", "convert_to_read(char)"),
            ("f_boolean", True, "convert_to_read(boolean)"),
            ("f_selection", "draft", "convert_to_read(selection)"),
        ]:
            field = self.Model._fields[fname]
            timer = _bench(lambda f=field, v=cache_val: f.convert_to_read(v, record))
            stats = timer.stats(label, warmup=0)
            _log_result(stats)
            self.results.append(stats)


@tagged("-standard", "orm_perf", "field_get")
class TestFieldGet(PerfTestCase):
    summary_title = "FIELD __GET__ SUMMARY"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Model = cls.env["test_performance.all_types"]
        cls.partner = cls.env["res.partner"].search([], limit=1)
        cls.record = cls.Model.create(
            {
                "name": "get_bench",
                "f_integer": 42,
                "f_float": 3.14,
                "f_monetary": 99.99,
                "f_boolean": True,
                "f_char": "hello world",
                "f_text": "longer text for benchmarking",
                "f_date": "2025-06-15",
                "f_datetime": "2025-06-15 10:30:00",
                "f_selection": "draft",
                "f_many2one": cls.partner.id,
                "f_json": {"key": "value"},
                "f_html": "<p>Hello</p>",
            }
        )
        cls.record.read(list(cls.Model._fields))

    def _bench_get(self, field_name, label=None, n=ITERATIONS):
        record = self.record
        label = label or f"__get__({field_name})"

        def bench():
            getattr(record, field_name)

        timer = _bench(bench, n=n)
        stats = timer.stats(label, warmup=0)
        self._log(stats)
        return stats

    def test_01_integer(self):
        self._bench_get("f_integer")

    def test_02_float(self):
        self._bench_get("f_float")

    def test_03_monetary(self):
        self._bench_get("f_monetary")

    def test_04_boolean(self):
        self._bench_get("f_boolean")

    def test_05_char(self):
        self._bench_get("f_char")

    def test_06_text(self):
        self._bench_get("f_text")

    def test_07_date(self):
        self._bench_get("f_date")

    def test_08_datetime(self):
        self._bench_get("f_datetime")

    def test_09_selection(self):
        self._bench_get("f_selection")

    def test_10_many2one(self):
        self._bench_get("f_many2one")

    def test_11_json(self):
        self._bench_get("f_json")

    def test_12_html(self):
        self._bench_get("f_html")

    def test_13_name(self):
        self._bench_get("name", "__get__(name/char)")

    def test_20_multi_field_access(self):
        record = self.record

        def bench():
            _ = record.f_integer
            _ = record.f_float
            _ = record.f_boolean
            _ = record.f_char
            _ = record.f_text
            _ = record.f_date
            _ = record.f_datetime
            _ = record.f_selection
            _ = record.f_monetary

        timer = _bench(bench, n=ITERATIONS)
        self._log(timer.stats("__get__(9_scalars_seq)", warmup=0))

    def test_21_multi_record_access(self):
        Base = self.env["test_performance.base"]
        records = Base.search([], limit=100)
        if len(records) < 100:
            Base.create(
                [{"name": f"multi_{i}", "value": i} for i in range(100 - len(records))]
            )
            records = Base.search([], limit=100)
        records.read(["value", "name"])

        def bench():
            for rec in records:
                _ = rec.value

        timer = _bench(bench, n=50, warmup=5)
        self._log(timer.stats("__get__(integer×100_records)", warmup=0))

    def test_30_specialized_vs_base(self):
        from odoo.orm.fields import misc, numeric, selection, temporal
        from odoo.orm.fields.base import Field

        record = self.record
        record.read(list(self.Model._fields))

        test_cases = [
            (numeric.Integer, "f_integer", "__get__(integer)"),
            (numeric.Float, "f_float", "__get__(float)"),
            (numeric.Monetary, "f_monetary", "__get__(monetary)"),
            (misc.Boolean, "f_boolean", "__get__(boolean)"),
            (selection.Selection, "f_selection", "__get__(selection)"),
            (temporal.Date, "f_date", "__get__(date)"),
            (temporal.Datetime, "f_datetime", "__get__(datetime)"),
        ]

        base_get = Field.__get__

        _logger.info("\n[ORM_PERF] === SPECIALIZED vs BASE Field.__get__ ===")
        _logger.info(
            "[ORM_PERF] %-20s %10s %10s %8s",
            "Field",
            "Spec p50",
            "Base p50",
            "Speedup",
        )
        _logger.info("[ORM_PERF] %s", "-" * 55)

        for _field_cls, fname, label in test_cases:
            field = self.Model._fields[fname]
            spec_get = type(field).__get__

            def bench_spec(f=field, r=record, g=spec_get):
                g(f, r)

            timer_spec = _bench(bench_spec, n=500, warmup=20)
            s_spec = timer_spec.stats(f"spec:{label}", warmup=0)

            def bench_base(f=field, r=record, g=base_get):
                g(f, r)

            timer_base = _bench(bench_base, n=500, warmup=20)
            s_base = timer_base.stats(f"base:{label}", warmup=0)

            speedup = (
                s_base["p50_us"] / s_spec["p50_us"]
                if s_spec["p50_us"] > 0
                else float("inf")
            )
            _logger.info(
                "[ORM_PERF] %-20s %9.1fµs %9.1fµs %7.2fx",
                fname,
                s_spec["p50_us"],
                s_base["p50_us"],
                speedup,
            )
            self.results.append(s_spec)
            self.results.append(s_base)


@tagged("-standard", "orm_perf")
class TestIteration(PerfTestCase):
    summary_title = "ITERATION SUMMARY"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Model = cls.env["test_performance.base"]
        existing = cls.Model.search_count([])
        if existing < 1000:
            cls.Model.create(
                [
                    {"name": f"iter_bench_{i}", "value": i}
                    for i in range(1000 - existing)
                ]
            )

    def test_01_iter_sizes(self):
        for size in (1, 10, 100, 1000):
            records = self.Model.search([], limit=size)

            def iterate(rs=records):
                for _ in rs:
                    pass

            timer = _bench(iterate, n=ITERATIONS if size <= 100 else 50)
            self._log(timer.stats(f"__iter__({size} records)", warmup=0))

    def test_02_browse(self):
        records = self.Model.search([], limit=100)
        ids = records.ids
        single_id = ids[0]

        timer = _bench(lambda: self.Model.browse(single_id))
        self._log(timer.stats("browse(single_int)", warmup=0))

        timer = _bench(lambda: self.Model.browse(ids))
        self._log(timer.stats("browse(100_ids)", warmup=0))

        timer = _bench(lambda: self.Model.browse(tuple(ids)))
        self._log(timer.stats("browse(100_tuple)", warmup=0))

    def test_03_hash(self):
        records = self.Model.search([], limit=100)
        single = records[0]

        timer = _bench(lambda: hash(single))
        self._log(timer.stats("__hash__(single)", warmup=0))

        timer = _bench(lambda: hash(records))
        self._log(timer.stats("__hash__(100)", warmup=0))

    def test_04_eq(self):
        r1 = self.Model.search([], limit=100)
        r2 = self.Model.search([], limit=100)
        r3 = self.Model.search([], limit=50)

        timer = _bench(lambda: r1 == r2)
        self._log(timer.stats("__eq__(same_100)", warmup=0))

        timer = _bench(lambda: r1 == r3)
        self._log(timer.stats("__eq__(diff_100v50)", warmup=0))

    def test_05_ids_property(self):
        records = self.Model.search([], limit=100)

        timer = _bench(lambda: records.ids)
        self._log(timer.stats(".ids(100)", warmup=0))

    def test_06_len(self):
        records = self.Model.search([], limit=100)

        timer = _bench(lambda: len(records))
        self._log(timer.stats("len(100)", warmup=0))

    def test_07_bool(self):
        records = self.Model.search([], limit=100)
        empty = self.Model.browse()

        timer = _bench(lambda: bool(records))
        self._log(timer.stats("bool(100_records)", warmup=0))

        timer = _bench(lambda: bool(empty))
        self._log(timer.stats("bool(empty)", warmup=0))

    def test_08_contains(self):
        records = self.Model.search([], limit=100)
        target = records[50]

        timer = _bench(lambda: target in records)
        self._log(timer.stats("__contains__(100)", warmup=0))

    def test_09_concat(self):
        r1 = self.Model.search([], limit=50)
        r2 = self.Model.search([], limit=50, offset=50)

        timer = _bench(lambda: r1 + r2)
        self._log(timer.stats("concat(50+50)", warmup=0))


@tagged("-standard", "orm_perf")
class TestCacheInternals(PerfTestCase):
    summary_title = "CACHE INTERNALS SUMMARY"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Model = cls.env["test_performance.base"]
        cls.AllTypes = cls.env["test_performance.all_types"]
        existing = cls.Model.search_count([])
        if existing < 100:
            cls.Model.create(
                [
                    {"name": f"cache_bench_{i}", "value": i}
                    for i in range(100 - existing)
                ]
            )

    def test_01_modified_simple(self):
        record = self.Model.search([], limit=1)
        field = self.Model._fields["value"]

        def bench():
            record.modified([field.name])

        timer = _bench(bench)
        self._log(timer.stats("modified(scalar_field)", warmup=0))

    def test_02_modified_relational(self):
        record = self.Model.search([("partner_id", "!=", False)], limit=1)
        if not record:
            return

        def bench():
            record.modified(["partner_id"])

        timer = _bench(bench)
        self._log(timer.stats("modified(many2one_field)", warmup=0))

    def test_03_modified_computed_chain(self):
        record = self.Model.search([], limit=1)

        def bench():
            record.modified(["value"])

        timer = _bench(bench)
        self._log(timer.stats("modified(computed_chain)", warmup=0))

    def test_04_flush_model_clean(self):
        records = self.Model.search([], limit=100)
        self.env.flush_all()

        def bench():
            records.flush_model()

        timer = _bench(bench)
        self._log(timer.stats("flush_model(clean)", warmup=0))

    def test_05_flush_model_dirty(self):
        record = self.Model.search([], limit=1)

        def bench():
            record.value += 1
            record.flush_model()

        timer = _bench(bench, n=50)
        self._log(timer.stats("flush_model(1_dirty)", warmup=0))

    def test_06_flush_all_clean(self):
        self.env.flush_all()

        def bench():
            self.env.flush_all()

        timer = _bench(bench)
        self._log(timer.stats("flush_all(clean)", warmup=0))

    def test_07_invalidate_all(self):
        records = self.Model.search([], limit=100)
        _ = records.mapped("name")

        def bench():
            self.env.invalidate_all()

        timer = _bench(bench)
        self._log(timer.stats("invalidate_all()", warmup=0))

    def test_08_invalidate_recordset(self):
        records = self.Model.search([], limit=100)
        _ = records.mapped("name")

        def bench():
            records.invalidate_recordset()

        timer = _bench(bench)
        self._log(timer.stats("invalidate_recordset(100)", warmup=0))

    def test_09_get_cache(self):
        field = self.Model._fields["name"]
        env = self.env

        timer = _bench(lambda: field._get_cache(env))
        self._log(timer.stats("Field._get_cache()", warmup=0))

    def test_10_update_cache(self):
        field = self.Model._fields["name"]
        record = self.Model.search([], limit=1)

        def bench():
            field._update_cache(record, "bench_value")

        timer = _bench(bench)
        self._log(timer.stats("Field._update_cache(1)", warmup=0))


@tagged("-standard", "orm_perf")
class TestUnlink(PerfTestCase):
    summary_title = "UNLINK SUMMARY"
    summary_sort = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Model = cls.env["test_performance.base"]

    def test_01_unlink_single(self):

        def bench():
            rec = self.Model.create({"name": "unlinkme"})
            rec.unlink()

        timer = _bench(bench, n=50, warmup=5)
        self._log(timer.stats("unlink(single)", warmup=0))

    def test_02_unlink_batch(self):

        def bench():
            recs = self.Model.create([{"name": f"unlinkme_{i}"} for i in range(10)])
            recs.unlink()

        timer = _bench(bench, n=30, warmup=3)
        self._log(timer.stats("unlink(batch_10)", warmup=0))


@tagged("-standard", "orm_perf")
class TestDomainPerf(PerfTestCase):
    summary_title = "DOMAIN SUMMARY"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Model = cls.env["test_performance.base"]

    def test_01_domain_construct_simple(self):
        leaf = [("name", "=", "test")]

        timer = _bench(lambda: Domain(leaf))
        self._log(timer.stats("Domain(simple_leaf)", warmup=0))

    def test_02_domain_construct_multi(self):
        leaves = [
            ("name", "=", "test"),
            ("value", ">", 10),
            ("active", "=", True),
        ]

        timer = _bench(lambda: Domain(leaves))
        self._log(timer.stats("Domain(3_leaves)", warmup=0))

    def test_03_domain_construct_nested(self):
        nested = [
            "|",
            ("name", "=", "a"),
            "&",
            ("value", ">", 10),
            ("active", "=", True),
        ]

        timer = _bench(lambda: Domain(nested))
        self._log(timer.stats("Domain(nested_or_and)", warmup=0))

    def test_04_domain_combine_and(self):
        d1 = Domain([("name", "=", "test")])
        d2 = Domain([("value", ">", 10)])

        timer = _bench(lambda: d1 & d2)
        self._log(timer.stats("Domain AND (&)", warmup=0))

    def test_05_domain_combine_or(self):
        d1 = Domain([("name", "=", "test")])
        d2 = Domain([("value", ">", 10)])

        timer = _bench(lambda: d1 | d2)
        self._log(timer.stats("Domain OR (|)", warmup=0))

    def test_06_domain_negate(self):
        d = Domain([("name", "=", "test")])

        timer = _bench(lambda: ~d)
        self._log(timer.stats("Domain NOT (~)", warmup=0))

    def test_07_domain_bool_true(self):
        timer = _bench(lambda: Domain(True))
        self._log(timer.stats("Domain(True)", warmup=0))

    def test_08_domain_bool_false(self):
        timer = _bench(lambda: Domain(False))
        self._log(timer.stats("Domain(False)", warmup=0))

    def test_10_domain_to_sql(self):
        domain = [("name", "like", "bench"), ("value", ">", 10)]
        model = self.Model.sudo()
        model.search(domain, limit=1)

        def bench():
            model._search(domain, limit=10)

        timer = _bench(bench, n=100)
        self._log(timer.stats("_search(2_leaf_domain)", warmup=0))

    def test_11_domain_to_sql_complex(self):
        domain = [
            "|",
            "&",
            ("name", "like", "bench"),
            ("value", ">", 10),
            "&",
            ("partner_id", "!=", False),
            ("value", "<", 50),
        ]
        model = self.Model.sudo()
        model.search(domain, limit=1)

        def bench():
            model._search(domain, limit=10)

        timer = _bench(bench, n=100)
        self._log(timer.stats("_search(complex_domain)", warmup=0))


@tagged("-standard", "orm_perf")
class TestReadGroupPerf(PerfTestCase):
    summary_title = "READ GROUP SUMMARY"
    summary_sort = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Model = cls.env["test_performance.base"]
        existing = cls.Model.search_count([])
        if existing < 100:
            cls.Model.create(
                [
                    {"name": f"rg_bench_{i}", "value": i % 20}
                    for i in range(100 - existing)
                ]
            )

    def test_01_read_group_simple(self):
        model = self.Model.sudo()

        def bench():
            model._read_group([], groupby=["value"], aggregates=["__count"])

        timer = _bench(bench, n=50)
        self._log(timer.stats("_read_group(group_by_value)", warmup=0))

    def test_02_read_group_with_domain(self):
        model = self.Model.sudo()

        def bench():
            model._read_group(
                [("value", ">", 5)], groupby=["value"], aggregates=["__count"]
            )

        timer = _bench(bench, n=50)
        self._log(timer.stats("_read_group(domain+group)", warmup=0))

    def test_03_read_group_multi_agg(self):
        model = self.Model.sudo()

        def bench():
            model._read_group(
                [],
                groupby=["partner_id"],
                aggregates=["__count", "value:sum", "value:avg"],
            )

        timer = _bench(bench, n=50)
        self._log(timer.stats("_read_group(multi_agg)", warmup=0))


@tagged("-standard", "orm_perf")
class TestHotPaths(PerfTestCase):
    summary_title = "HOT-PATH SUMMARY"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Model = cls.env["test_performance.base"]
        cls.AllTypes = cls.env["test_performance.all_types"]
        existing = cls.Model.search_count([])
        if existing < 200:
            cls.Model.create(
                [{"name": f"hp_bench_{i}", "value": i} for i in range(200 - existing)]
            )

    def test_01_read_format_10_records(self):
        records = self.Model.search([], limit=10)
        fnames = ["name", "value", "partner_id"]

        def bench():
            self.env.invalidate_all()
            records.read(fnames)

        timer = _bench(bench, n=100, warmup=10)
        self._log(timer.stats("read(10rec×3fields)", warmup=0))

    def test_02_read_format_100_records(self):
        records = self.Model.search([], limit=100)
        fnames = ["name", "value", "partner_id"]

        def bench():
            self.env.invalidate_all()
            records.read(fnames)

        timer = _bench(bench, n=50, warmup=5)
        self._log(timer.stats("read(100rec×3fields)", warmup=0))

    def test_03_read_format_cached(self):
        records = self.Model.search([], limit=100)
        fnames = ["name", "value", "partner_id"]
        records.read(fnames)

        def bench():
            records.read(fnames)

        timer = _bench(bench, n=200, warmup=10)
        self._log(timer.stats("read(100rec×3fields,cached)", warmup=0))

    def test_10_grouped_by_field(self):
        records = self.Model.search([], limit=100)
        _ = records.mapped("value")

        def bench():
            records.grouped("value")

        timer = _bench(bench, n=100, warmup=10)
        self._log(timer.stats("grouped(field,100)", warmup=0))

    def test_11_grouped_by_lambda(self):
        records = self.Model.search([], limit=100)
        _ = records.mapped("value")

        def bench():
            records.grouped(lambda r: r.value % 10)

        timer = _bench(bench, n=100, warmup=10)
        self._log(timer.stats("grouped(lambda,100)", warmup=0))

    def test_20_to_prefetch(self):
        records = self.Model.search([], limit=200)
        field = self.Model._fields["name"]
        record = records[0]
        records.read(["name"])

        def bench():
            field._to_prefetch(record)

        timer = _bench(bench, n=200, warmup=10)
        self._log(timer.stats("_to_prefetch(200,all_cached)", warmup=0))

    def test_21_to_prefetch_cold(self):
        records = self.Model.search([], limit=200)
        field = self.Model._fields["name"]
        record = records[0]

        def bench():
            self.env.invalidate_all()
            field._to_prefetch(record)

        timer = _bench(bench, n=100, warmup=10)
        self._log(timer.stats("_to_prefetch(200,cold)", warmup=0))

    def test_30_ensure_computed_noop(self):
        records = self.Model.search([], limit=100)
        field = self.Model._fields["value_pc"]
        self.env.flush_all()

        def bench():
            field.ensure_computed(records)

        timer = _bench(bench, n=500, warmup=20)
        self._log(timer.stats("ensure_computed(noop)", warmup=0))

    def test_31_ensure_computed_non_stored(self):
        records = self.Model.search([], limit=100)
        field = self.Model._fields["computed_value"]

        def bench():
            field.ensure_computed(records)

        timer = _bench(bench, n=500, warmup=20)
        self._log(timer.stats("ensure_computed(non_stored)", warmup=0))


@tagged("-standard", "orm_perf")
class TestFullPipeline(PerfTestCase):
    summary_title = "FULL PIPELINE SUMMARY"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Model = cls.env["test_performance.all_types"]

    def test_01_create_all_types(self):
        partner = self.env["res.partner"].search([], limit=1)
        vals = {
            "name": "fullpipe",
            "f_integer": 42,
            "f_float": 3.14,
            "f_char": "hello",
            "f_text": "A longer text value.",
            "f_boolean": True,
            "f_date": "2025-06-15",
            "f_datetime": "2025-06-15 10:30:00",
            "f_selection": "open",
            "f_json": {"key": "value"},
            "f_many2one": partner.id,
        }

        counter = [0]

        def bench():
            counter[0] += 1
            v = dict(vals)
            v["name"] = f"fullpipe_{counter[0]}"
            self.Model.create(v)

        timer = _bench(bench, n=30, warmup=3)
        self._log(timer.stats("create(all_types)", warmup=0))

    def test_02_write_all_types(self):
        record = self.Model.create({"name": "write_bench"})

        counter = [0]

        def bench():
            counter[0] += 1
            record.write(
                {
                    "f_integer": counter[0],
                    "f_char": f"updated_{counter[0]}",
                    "f_selection": "open" if counter[0] % 2 else "draft",
                    "f_date": "2025-07-01",
                }
            )

        timer = _bench(bench, n=50, warmup=5)
        self._log(timer.stats("write(4_mixed_fields)", warmup=0))

    def test_03_read_all_types(self):
        record = self.Model.create(
            {
                "name": "read_bench",
                "f_integer": 42,
                "f_char": "test",
                "f_date": "2025-06-15",
                "f_selection": "open",
            }
        )

        fnames = [
            "name",
            "f_integer",
            "f_float",
            "f_char",
            "f_text",
            "f_boolean",
            "f_date",
            "f_datetime",
            "f_selection",
        ]

        def bench():
            self.env.invalidate_all()
            record.read(fnames)

        timer = _bench(bench, n=50, warmup=5)
        self._log(timer.stats("read(9_fields)", warmup=0))

    def test_04_search_fetch(self):
        for i in range(20):
            self.Model.create({"name": f"sf_{i}", "f_integer": i})
        model = self.Model.sudo()

        def bench():
            self.env.invalidate_all()
            model.search_fetch(
                [("f_integer", ">", 5)],
                ["name", "f_integer", "f_char"],
                limit=50,
            )

        timer = _bench(bench, n=50, warmup=5)
        self._log(timer.stats("search_fetch(3_fields)", warmup=0))

    #: The orm_perf suites this aggregate report covers -- deliberately
    #: not the accel_baseline ones (TestAccelClone and friends), which
    #: answer a different question and were never part of this report.
    _AGGREGATE_CLASSES = (
        "TestFieldConversion",
        "TestFieldGet",
        "TestIteration",
        "TestCacheInternals",
        "TestUnlink",
        "TestDomainPerf",
        "TestReadGroupPerf",
        "TestHotPaths",
        "TestFullPipeline",
    )

    def test_99_summary(self):
        super().test_99_summary()

        # _RESULTS_REGISTRY is populated by PerfTestCase.setUpClass for
        # every suite that ran, so this reads it by name instead of
        # getattr(SiblingClass, "results", []) on each class object --
        # the same run-order/selection dependency remains (a class that
        # never ran has nothing to read), but this no longer needs to
        # import/name each sibling class object directly, or risk an
        # AttributeError reaching into one that was never set up.
        all_results = []
        for cls_name in self._AGGREGATE_CLASSES:
            all_results.extend(_RESULTS_REGISTRY.get(cls_name, []))

        if all_results:
            _logger.info(
                "\n[ORM_PERF] === AGGREGATE REPORT (%d benchmarks) ===",
                len(all_results),
            )
            _logger.info("[ORM_PERF] TOP 20 SLOWEST (by p50):")
            by_time = sorted(
                all_results, key=lambda r: r.get("p50_us", 0), reverse=True
            )
            for r in by_time[:20]:
                _logger.info("[ORM_PERF]   %s", r.get("summary", ""))

            _logger.info("\n[ORM_PERF] JSON Export:")
            export = {
                "timestamp": datetime.now().isoformat(),
                "total_benchmarks": len(all_results),
                "results": all_results,
            }
            _logger.info(json.dumps(export, indent=2, default=str))


@tagged("-standard", "accel_baseline")
class TestAccelClone(PerfTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.flat_small = {
            "id": 1,
            "name": "test",
            "active": True,
            "value": 3.14,
        }
        cls.flat_large = {f"field_{i}": f"value_{i}" for i in range(50)}
        cls.nested = {
            "id": 1,
            "partner": {
                "id": 10,
                "name": "P",
                "country": {"id": 5, "code": "MX"},
            },
            "lines": [
                {
                    "id": j,
                    "product": {"id": j * 10, "name": f"prod_{j}"},
                    "qty": j * 1.5,
                }
                for j in range(10)
            ],
        }
        cls.list_of_dicts = [
            {"id": i, "name": f"rec_{i}", "val": i * 0.1, "active": i % 2 == 0}
            for i in range(100)
        ]
        cls.properties_blob = {
            "definitions": [
                {
                    "name": f"prop_{i}",
                    "type": "char" if i % 3 == 0 else "integer",
                    "string": f"Property {i}",
                    "default": f"default_{i}" if i % 3 == 0 else i,
                }
                for i in range(20)
            ],
            "values": {f"prop_{i}": f"val_{i}" if i % 3 == 0 else i for i in range(20)},
        }

    def test_01_clone_flat_small(self):
        from odoo.libs.json import fast_clone

        data = self.flat_small
        timer = _bench(lambda: fast_clone(data))
        self._log(timer.stats("fast_clone(flat_4keys)", warmup=0))

    def test_02_clone_flat_large(self):
        from odoo.libs.json import fast_clone

        data = self.flat_large
        timer = _bench(lambda: fast_clone(data))
        self._log(timer.stats("fast_clone(flat_50keys)", warmup=0))

    def test_03_clone_nested(self):
        from odoo.libs.json import fast_clone

        data = self.nested
        timer = _bench(lambda: fast_clone(data))
        self._log(timer.stats("fast_clone(nested_3lvl)", warmup=0))

    def test_04_clone_list_of_dicts(self):
        from odoo.libs.json import fast_clone

        data = self.list_of_dicts
        timer = _bench(lambda: fast_clone(data))
        self._log(timer.stats("fast_clone(100_dicts)", warmup=0))

    def test_05_clone_properties(self):
        from odoo.libs.json import fast_clone

        data = self.properties_blob
        timer = _bench(lambda: fast_clone(data))
        self._log(timer.stats("fast_clone(properties)", warmup=0))

    def test_10_deepcopy_flat_small(self):
        import copy

        data = self.flat_small
        timer = _bench(lambda: copy.deepcopy(data))
        self._log(timer.stats("deepcopy(flat_4keys)", warmup=0))

    def test_11_deepcopy_nested(self):
        import copy

        data = self.nested
        timer = _bench(lambda: copy.deepcopy(data))
        self._log(timer.stats("deepcopy(nested_3lvl)", warmup=0))

    def test_12_deepcopy_list_of_dicts(self):
        import copy

        data = self.list_of_dicts
        timer = _bench(lambda: copy.deepcopy(data))
        self._log(timer.stats("deepcopy(100_dicts)", warmup=0))

    def test_13_deepcopy_properties(self):
        import copy

        data = self.properties_blob
        timer = _bench(lambda: copy.deepcopy(data))
        self._log(timer.stats("deepcopy(properties)", warmup=0))

    def test_99_summary(self):
        if not self.results:
            return
        _logger.info("\n[ORM_PERF] === CLONE BASELINE ===")
        clones = [r for r in self.results if "fast_clone" in r.get("name", "")]
        deeps = [r for r in self.results if "deepcopy" in r.get("name", "")]
        for r in sorted(clones, key=lambda x: x.get("p50_us", 0)):
            _logger.info("[ORM_PERF]   %s", r.get("summary", ""))
        for r in sorted(deeps, key=lambda x: x.get("p50_us", 0)):
            _logger.info("[ORM_PERF]   %s", r.get("summary", ""))


@tagged("-standard", "accel_baseline")
class TestAccelMappedFiltered(PerfTestCase):
    summary_title = "MAPPED/FILTERED/SORTED BASELINE"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Model = cls.env["test_performance.base"]
        existing = cls.Model.search_count([])
        if existing < 1000:
            cls.Model.create(
                [{"name": f"mf_{i}", "value": i} for i in range(1000 - existing)]
            )

    def test_01_mapped_int_10(self):
        records = self.Model.search([], limit=10)
        records.read(["value"])
        timer = _bench(lambda: records.mapped("value"))
        self._log(timer.stats("mapped('value',10)", warmup=0))

    def test_02_mapped_int_100(self):
        records = self.Model.search([], limit=100)
        records.read(["value"])
        timer = _bench(lambda: records.mapped("value"))
        self._log(timer.stats("mapped('value',100)", warmup=0))

    def test_03_mapped_int_1000(self):
        records = self.Model.search([], limit=1000)
        records.read(["value"])
        timer = _bench(lambda: records.mapped("value"), n=100)
        self._log(timer.stats("mapped('value',1000)", warmup=0))

    def test_04_mapped_char_100(self):
        records = self.Model.search([], limit=100)
        records.read(["name"])
        timer = _bench(lambda: records.mapped("name"))
        self._log(timer.stats("mapped('name',100)", warmup=0))

    def test_05_mapped_m2o_100(self):
        records = self.Model.search([], limit=100)
        records.read(["partner_id"])
        timer = _bench(lambda: records.mapped("partner_id"), n=100)
        self._log(timer.stats("mapped('partner_id',100)", warmup=0))

    def test_10_filtered_int_100(self):
        records = self.Model.search([], limit=100)
        records.read(["value"])
        timer = _bench(lambda: records.filtered("value"))
        self._log(timer.stats("filtered('value',100)", warmup=0))

    def test_11_filtered_int_1000(self):
        records = self.Model.search([], limit=1000)
        records.read(["value"])
        timer = _bench(lambda: records.filtered("value"), n=100)
        self._log(timer.stats("filtered('value',1000)", warmup=0))

    def test_12_filtered_name_100(self):
        records = self.Model.search([], limit=100)
        records.read(["name"])
        timer = _bench(lambda: records.filtered("name"))
        self._log(timer.stats("filtered('name',100)", warmup=0))

    def test_13_filtered_lambda_100(self):
        records = self.Model.search([], limit=100)
        records.read(["value"])
        timer = _bench(lambda: records.filtered(lambda r: r.value))
        self._log(timer.stats("filtered(lambda,100)", warmup=0))

    def test_20_sorted_field_100(self):
        records = self.Model.search([], limit=100)
        records.read(["value"])
        timer = _bench(lambda: records.sorted("value"), n=100)
        self._log(timer.stats("sorted('value',100)", warmup=0))

    def test_21_sorted_field_1000(self):
        records = self.Model.search([], limit=1000)
        records.read(["value"])
        timer = _bench(lambda: records.sorted("value"), n=50)
        self._log(timer.stats("sorted('value',1000)", warmup=0))

    def test_22_sorted_reverse_100(self):
        records = self.Model.search([], limit=100)
        records.read(["value"])
        timer = _bench(lambda: records.sorted("value", reverse=True), n=100)
        self._log(timer.stats("sorted('value',100,rev)", warmup=0))

    def test_23_sorted_lambda_100(self):
        records = self.Model.search([], limit=100)
        records.read(["value"])
        timer = _bench(lambda: records.sorted(lambda r: r.value), n=100)
        self._log(timer.stats("sorted(lambda,100)", warmup=0))


@tagged("-standard", "accel_baseline")
class TestAccelFieldCache(PerfTestCase):
    summary_title = "FIELDCACHE STANDALONE BASELINE"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def _make_cache(self, n_records=1000):
        from odoo.orm.components.cache import FieldCache

        cache = FieldCache()
        f = "field_0"
        ids = tuple(range(1, n_records + 1))
        for id_ in ids:
            cache.set_value(f, id_, f"v_{id_}")
        return cache, f, ids

    def test_01_get_value_hit(self):
        cache, f, _ = self._make_cache(1000)
        timer = _bench(lambda: cache.get_value(f, 500))
        self._log(timer.stats("cache.get_value(hit)", warmup=0))

    def test_02_get_value_miss(self):
        cache, f, _ = self._make_cache(1000)
        timer = _bench(lambda: cache.get_value(f, 99999, None))
        self._log(timer.stats("cache.get_value(miss)", warmup=0))

    def test_03_set_value(self):
        from odoo.orm.components.cache import FieldCache

        cache = FieldCache()
        f = "test"
        ctr = [0]

        def bench():
            ctr[0] += 1
            cache.set_value(f, ctr[0], ctr[0])

        timer = _bench(bench)
        self._log(timer.stats("cache.set_value()", warmup=0))

    def test_04_insert_if_absent_100(self):
        from odoo.orm.components.cache import FieldCache

        cache = FieldCache()
        d = cache.get_field_data("test")
        ids = tuple(range(100))
        vals = tuple(range(100))
        timer = _bench(
            lambda: deque(map(d.setdefault, ids, vals, strict=True), maxlen=0)
        )
        self._log(timer.stats("insert_if_absent(100)", warmup=0))

    def test_05_insert_if_absent_1000(self):
        from odoo.orm.components.cache import FieldCache

        cache = FieldCache()
        d = cache.get_field_data("test")
        ids = tuple(range(1000))
        vals = tuple(range(1000))
        timer = _bench(
            lambda: deque(map(d.setdefault, ids, vals, strict=True), maxlen=0)
        )
        self._log(timer.stats("insert_if_absent(1000)", warmup=0))

    def test_06_update_batch_1(self):
        cache, f, _ = self._make_cache(100)
        d = cache.get_field_data(f)
        timer = _bench(lambda: d.update(dict.fromkeys((42,), "x")))
        self._log(timer.stats("update_batch(1)", warmup=0))

    def test_07_update_batch_100(self):
        cache, f, ids = self._make_cache(100)
        d = cache.get_field_data(f)
        timer = _bench(lambda: d.update(dict.fromkeys(ids, "x")))
        self._log(timer.stats("update_batch(100)", warmup=0))

    def test_08_update_batch_1000(self):
        from odoo.orm.components.cache import FieldCache

        cache = FieldCache()
        d = cache.get_field_data("test")
        ids = tuple(range(1000))
        timer = _bench(lambda: d.update(dict.fromkeys(ids, "x")))
        self._log(timer.stats("update_batch(1000)", warmup=0))

    def test_09_invalidate_100(self):
        cache, f, ids = self._make_cache(1000)
        inv_ids = ids[:100]

        def bench():
            for id_ in inv_ids:
                cache.set_value(f, id_, "x")
            cache.invalidate_field(f, inv_ids)

        timer = _bench(bench, n=ITERATIONS)
        self._log(timer.stats("cache.invalidate(100of1000)", warmup=0))

    def test_10_mark_dirty_100(self):
        from odoo.orm.components.cache import FieldCache

        cache = FieldCache()
        f = "test"
        ids = list(range(100))
        timer = _bench(lambda: cache.mark_dirty(f, ids))
        self._log(timer.stats("cache.mark_dirty(100)", warmup=0))


@tagged("-standard", "accel_baseline")
class TestAccelPrimitives(PerfTestCase):
    summary_title = "PRIMITIVES BASELINE"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_01_newid_create(self):
        from odoo.orm.primitives import NewId

        timer = _bench(lambda: NewId(origin=42))
        self._log(timer.stats("NewId(origin=42)", warmup=0))

    def test_02_newid_hash(self):
        from odoo.orm.primitives import NewId

        nid = NewId(origin=42)
        timer = _bench(lambda: hash(nid))
        self._log(timer.stats("hash(NewId)", warmup=0))

    def test_03_newid_eq(self):
        from odoo.orm.primitives import NewId

        a, b = NewId(origin=42), NewId(origin=42)
        timer = _bench(lambda: a == b)
        self._log(timer.stats("NewId.__eq__(same)", warmup=0))

    def test_04_newid_lt_int(self):
        from odoo.orm.primitives import NewId

        nid = NewId(origin=10)
        timer = _bench(lambda: nid < 20)
        self._log(timer.stats("NewId.__lt__(int)", warmup=0))

    def test_10_originids_int(self):
        from odoo.orm.helpers import _origin_ids

        ids = tuple(range(1, 1001))
        timer = _bench(lambda: _origin_ids(ids), n=ITERATIONS)
        self._log(timer.stats("origin_ids(1000_int)", warmup=0))

    def test_11_originids_mixed(self):
        from odoo.orm.helpers import _origin_ids
        from odoo.orm.primitives import NewId

        ids = tuple(NewId(origin=i) if i % 3 == 0 else i for i in range(1, 501))
        timer = _bench(lambda: _origin_ids(ids), n=ITERATIONS)
        self._log(timer.stats("origin_ids(500_mixed)", warmup=0))

    def test_12_originids_all_newid(self):
        from odoo.orm.helpers import _origin_ids
        from odoo.orm.primitives import NewId

        ids = tuple(NewId(origin=i) for i in range(1, 501))
        timer = _bench(lambda: _origin_ids(ids), n=ITERATIONS)
        self._log(timer.stats("origin_ids(500_newid)", warmup=0))
