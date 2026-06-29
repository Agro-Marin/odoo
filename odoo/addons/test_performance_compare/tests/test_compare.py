"""Portable cross-version ORM benchmark.

Runs a fixed battery of ORM operations through public APIs only, captures both
timing and query counts for each, and writes a single labelled JSON report.

Run on each build (fork and a vanilla 19.0 checkout) and diff with ``compare.py``::

    BENCH_LABEL=marin BENCH_OUT=/tmp/marin.json \\
        odoo-bin -c <conf> -d <db> -i test_performance_compare \\
        --test-tags /test_performance_compare --stop-after-init --workers=0

The suite is one orchestrating test (``test_benchmark_suite``) so a run always
produces a *complete* report regardless of test ordering, and so every operation
sees the same, freshly built corpus.
"""

import logging

from odoo.tests.common import TransactionCase, tagged

from .perfkit import BenchmarkRecorder

_logger = logging.getLogger(__name__)

# Corpus sizing — kept modest so the run is quick but large enough that
# per-record Python overhead dominates fixed costs.
CORPUS = 200
HOT = 100  # subset used for read/recordset benchmarks
N_REL = 10
N_TAGS = 10


@tagged("post_install", "-at_install", "perf_compare")
class TestPerfCompare(TransactionCase):
    """Self-contained ORM benchmark, identical on fork and upstream 19.0."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Base = cls.env["perf.cmp.base"]
        cls.Line = cls.env["perf.cmp.line"]
        cls.Rel = cls.env["perf.cmp.rel"]
        cls.Tag = cls.env["perf.cmp.tag"]

        cls.rels = cls.Rel.create([{"name": f"rel_{i}"} for i in range(N_REL)])
        cls.tags = cls.Tag.create([{"name": f"tag_{i}"} for i in range(N_TAGS)])
        rel_ids = cls.rels.ids

        cls.Base.create(
            [
                {
                    "name": f"base_{i}",
                    "value": i,
                    "amount": i * 1.5,
                    "state": ("draft", "open", "done", "cancel")[i % 4],
                    "rel_id": rel_ids[i % N_REL],
                    # first 50 records get a few lines for o2m/total benchmarks
                    "line_ids": (
                        [(0, 0, {"value": j}) for j in range(3)] if i < 50 else []
                    ),
                }
                for i in range(CORPUS)
            ]
        )
        cls.env.flush_all()

    def _corpus(self):
        recs = self.Base.search([], limit=CORPUS, order="id")
        return recs, recs[:HOT]

    # -- the suite ------------------------------------------------------------

    def test_benchmark_suite(self):
        env = self.env
        rec = BenchmarkRecorder(self.cr, logger=_logger)
        all_recs, hot = self._corpus()
        hot_ids = hot.ids
        single = hot[0]
        Base = self.Base

        # warm everything once
        all_recs.mapped("value")
        all_recs.mapped("rel_id")

        # === SEARCH (clean corpus, before any mutation) =====================
        rec.measure(
            "search.empty_limit100",
            lambda: Base.search([], limit=100),
            group="search",
            invalidate=env.invalidate_all,
        )
        rec.measure(
            "search.domain_value_gt",
            lambda: Base.search([("value", ">", 50)], limit=100),
            group="search",
            invalidate=env.invalidate_all,
        )
        rec.measure(
            "search.count",
            lambda: Base.search_count([("value", ">", 50)]),
            group="search",
            invalidate=env.invalidate_all,
        )
        rec.measure(
            "search.read_3fields_100",
            lambda: Base.search_read(
                [("value", ">", 50)], ["name", "value", "rel_id"], limit=100
            ),
            group="search",
            invalidate=env.invalidate_all,
        )

        # === READ ============================================================
        read_recs = Base.browse(hot_ids)
        rec.measure(
            "read.cold_100x3",
            lambda: read_recs.read(["name", "value", "rel_id"]),
            group="read",
            invalidate=env.invalidate_all,
        )
        # warm read: no invalidation between iterations
        read_recs.read(["name", "value", "rel_id"])
        rec.measure(
            "read.warm_100x3",
            lambda: read_recs.read(["name", "value", "rel_id"]),
            group="read",
        )
        rec.measure(
            "read.m2o_access_100",
            lambda: [r.rel_id.name for r in read_recs],
            group="read",
            invalidate=env.invalidate_all,
        )
        _ = single.value  # warm
        rec.measure(
            "field.access_scalar_cached",
            lambda: single.value,
            group="read",
            iterations=400,
            warmup=40,
        )

        # === RECORDSET OPS (pure Python, cache warm) ========================
        read_recs.read(["name", "value", "rel_id"])
        rec.measure(
            "mapped.scalar_100",
            lambda: read_recs.mapped("value"),
            group="recordset",
        )
        rec.measure(
            "mapped.m2o_100",
            lambda: read_recs.mapped("rel_id"),
            group="recordset",
        )
        rec.measure(
            "filtered.field_100",
            lambda: read_recs.filtered("flag"),
            group="recordset",
        )
        rec.measure(
            "filtered.lambda_100",
            lambda: read_recs.filtered(lambda r: r.value > 50),
            group="recordset",
        )
        rec.measure(
            "sorted.field_100",
            lambda: read_recs.sorted("value"),
            group="recordset",
        )
        rec.measure(
            "iterate_100",
            lambda: [None for _ in read_recs],
            group="recordset",
        )

        # === READ GROUP ======================================================
        try:
            Base._read_group([], groupby=["state"], aggregates=["__count"])
        except Exception:  # pragma: no cover - signature guard for portability
            _logger.warning("[PERF_CMP] _read_group unavailable; skipping group")
        else:
            rec.measure(
                "read_group.by_state",
                lambda: Base._read_group(
                    [], groupby=["state"], aggregates=["__count"]
                ),
                group="read_group",
                invalidate=env.invalidate_all,
            )
            rec.measure(
                "read_group.by_state_sum",
                lambda: Base._read_group(
                    [], groupby=["state"], aggregates=["__count", "value:sum"]
                ),
                group="read_group",
                invalidate=env.invalidate_all,
            )

        # === WRITE (mutates corpus; runs after all reads) ===================
        counter = [0]

        def _write_recompute():
            counter[0] += 1
            single.write({"value": counter[0]})  # triggers stored value_pc
            env.flush_all()

        rec.measure("write.single_recompute", _write_recompute, group="write")

        def _write_plain():
            counter[0] += 1
            single.write({"name": f"x_{counter[0]}"})  # no recompute
            env.flush_all()

        rec.measure("write.single_norecompute", _write_plain, group="write")

        batch = Base.browse(hot_ids)

        def _write_batch():
            counter[0] += 1
            batch.write({"flag": counter[0] % 2 == 0})
            env.flush_all()

        rec.measure(
            "write.batch100", _write_batch, group="write", iterations=40, warmup=5
        )

        def _assign():
            counter[0] += 1
            single.value = counter[0]
            env.flush_all()

        rec.measure("write.assign_scalar", _assign, group="write")

        # === CREATE ==========================================================
        cc = [0]

        def _create_single():
            cc[0] += 1
            Base.create({"name": f"c_{cc[0]}", "value": cc[0]})
            env.flush_all()

        rec.measure(
            "create.single", _create_single, group="create", iterations=40, warmup=5
        )

        def _create_batch():
            cc[0] += 1
            Base.create([{"name": f"cb_{cc[0]}_{i}", "value": i} for i in range(100)])
            env.flush_all()

        rec.measure(
            "create.batch100", _create_batch, group="create", iterations=15, warmup=3
        )

        def _create_lines():
            cc[0] += 1
            Base.create(
                {
                    "name": f"cl_{cc[0]}",
                    "line_ids": [(0, 0, {"value": j}) for j in range(10)],
                }
            )
            env.flush_all()

        rec.measure(
            "create.with_lines10",
            _create_lines,
            group="create",
            iterations=30,
            warmup=5,
        )

        tag_ids = self.tags.ids

        def _create_tags():
            cc[0] += 1
            Base.create(
                {"name": f"ct_{cc[0]}", "tag_ids": [(6, 0, tag_ids)]}
            )
            env.flush_all()

        rec.measure(
            "create.with_tags10",
            _create_tags,
            group="create",
            iterations=30,
            warmup=5,
        )

        # === UNLINK (setup builds the victim each iteration, untimed) =======
        victim = [None]

        def _mk_single():
            victim[0] = Base.create({"name": "u"})
            env.flush_all()

        def _unlink_single():
            victim[0].unlink()

        rec.measure(
            "unlink.single",
            _unlink_single,
            group="unlink",
            setup=_mk_single,
            iterations=40,
            warmup=5,
        )

        victims = [None]

        def _mk_batch():
            victims[0] = Base.create([{"name": f"ub_{i}"} for i in range(10)])
            env.flush_all()

        def _unlink_batch():
            victims[0].unlink()

        rec.measure(
            "unlink.batch10",
            _unlink_batch,
            group="unlink",
            setup=_mk_batch,
            iterations=30,
            warmup=5,
        )

        # === persist =========================================================
        # Timestamp is informational only (never a comparison key); fetched from
        # the DB clock so the test stays free of an in-process wall-clock call.
        self.cr.execute("SELECT now()")
        timestamp = self.cr.fetchone()[0].isoformat()
        path = rec.write(timestamp)
        _logger.info(
            "[PERF_CMP] suite complete: %d benchmarks, label=%r -> %s",
            len(rec.results),
            rec.report(timestamp)["meta"]["label"],
            path,
        )
        # sanity: we actually produced the expected battery
        self.assertGreaterEqual(len(rec.results), 20)
