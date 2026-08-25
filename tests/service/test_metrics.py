"""Pure-pytest tests for ``odoo.service._metrics``.

Covers the Prometheus exposition without a live server, database or scrape:
gauge collection against stand-in server objects, exposition-format validity,
label escaping, and the never-raise contract.

Run with::

    python -m pytest tests/service/test_metrics.py -v
"""

import os
import re
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(scope="module")
def mod():
    """Return ``odoo.service._metrics``, imported once per session."""
    import odoo.service._metrics as m

    return m


@pytest.fixture
def pooled_db():
    """Return ``odoo.db``, skipping if it cannot report pool health yet.

    The pool half of the exposition reads :func:`odoo.db.pool_health`.  Skipping
    rather than faking it with ``create=True``: a mock conjured onto a module
    that does not export the function would assert the renderer works against an
    interface this checkout does not have, and pass while the real thing was
    missing.  ``render_prometheus`` already degrades to an empty pool section in
    that case, which the never-raise test covers without needing the attribute.
    """
    from odoo import db

    if not hasattr(db, "pool_health"):
        pytest.skip("odoo.db.pool_health is not present in this checkout")
    return db


METRIC_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
SAMPLE = re.compile(
    r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{.*\})? (-?[0-9.eE+]+|NaN|\+Inf|-Inf)$"
)


def parse_exposition(text: str) -> tuple[dict[str, str], list[str]]:
    """Return ``(declared_types, errors)`` for a Prometheus text payload."""
    declared: dict[str, str] = {}
    sampled: set[str] = set()
    errors: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line:
            continue
        if line.startswith(("# HELP ", "# TYPE ")):
            name = line.split(" ", 3)[2]
            if not METRIC_NAME.match(name):
                errors.append(f"{lineno}: invalid metric name {name!r}")
            if line.startswith("# TYPE "):
                if name in declared:
                    errors.append(f"{lineno}: duplicate TYPE for {name}")
                if name in sampled:
                    errors.append(f"{lineno}: TYPE for {name} follows its samples")
                declared[name] = line.rsplit(" ", 1)[1]
            continue
        match = SAMPLE.match(line)
        if not match:
            errors.append(f"{lineno}: unparseable sample {line!r}")
            continue
        name, labels = match.group(1), match.group(2)
        sampled.add(name)
        base = name.removesuffix("_bucket").removesuffix("_sum").removesuffix("_count")
        if name not in declared and base not in declared:
            errors.append(f"{lineno}: sample {name} has no TYPE")
        errors.extend(
            f"{lineno}: invalid label name {key!r}"
            for key in re.findall(r'([^,{ ]+)="', labels or "")
            if not METRIC_NAME.match(key)
        )
    return declared, errors


class TestServiceMetrics:
    """``service_metrics`` reads the live server without ever being the failure."""

    def test_no_server_yet_reports_flavor_none(self, mod):
        """A scrape before ``lifecycle.start()`` must answer, not raise."""
        from odoo.service import lifecycle

        with patch.object(lifecycle, "server", None):
            out = mod.service_metrics()
        assert out["flavor"] == "none"
        assert "registries" in out

    def test_prefork_reports_worker_counts(self, mod):
        from odoo.service import lifecycle

        server = MagicMock()
        type(server).__name__ = "PreforkServer"
        server.workers = {1: object(), 2: object()}
        server.workers_http = {1: object(), 2: object()}
        server.workers_cron = {3: object()}
        server.workers_job = {}
        server.population = 4
        server.generation = 17
        server.long_polling_pid = 999
        server.pid = os.getpid()  # this process IS the master

        with patch.object(lifecycle, "server", server):
            out = mod.service_metrics()
        assert out["flavor"] == "prefork"
        assert out["workers"] == {"http": 2, "cron": 1, "job": 0}
        assert out["worker_population"] == 4
        assert out["worker_generation"] == 17
        assert out["long_polling_alive"] is True

    def test_forked_worker_omits_the_master_only_gauges(self, mod):
        """A prefork worker inherits the master's PreforkServer through
        ``os.fork()``; every fleet counter on it is frozen at the instant of the
        fork.  The worker must publish none of them rather than publish a stale
        view that disagrees with every other worker.
        """
        from odoo.service import lifecycle

        server = MagicMock()
        type(server).__name__ = "PreforkServer"
        server.workers_http = {1: object(), 2: object()}
        server.workers_cron = {3: object()}
        server.workers_job = {}
        server.population = 4
        server.generation = 17
        server.long_polling_pid = 999
        server.pid = os.getpid() + 1  # a child: master pid inherited at fork

        with patch.object(lifecycle, "server", server):
            out = mod.service_metrics()
        assert out["flavor"] == "prefork"
        for key in (
            "workers",
            "worker_population",
            "worker_generation",
            "long_polling_alive",
        ):
            assert key not in out, f"{key} is master-only but a worker emitted it"

        with patch.object(lifecycle, "server", server):
            text = mod.render_prometheus()
        for family in (
            "odoo_workers",
            "odoo_worker_population",
            "odoo_worker_generation",
            "odoo_long_polling_alive",
        ):
            assert family not in text
        _, errors = parse_exposition(text)
        assert not errors, errors

    def test_threaded_reports_thread_counts_and_slot_ceiling(self, mod):
        import threading

        from odoo.service import lifecycle

        server = MagicMock(spec=["httpd", "limits_reached_threads"])
        type(server).__name__ = "ThreadedServer"
        server.httpd.max_http_threads = 31
        server.limits_reached_threads = set()

        marker = threading.current_thread()
        original = getattr(marker, "type", None)
        marker.type = "http"
        try:
            with patch.object(lifecycle, "server", server):
                out = mod.service_metrics()
        finally:
            if original is None:
                del marker.type
            else:
                marker.type = original

        assert out["flavor"] == "threaded"
        assert out["http_threads_max"] == 31
        assert out["threads"]["http"] >= 1
        assert set(out["threads"]) == {"http", "cron", "job"}


class TestPrometheusExposition:
    """The rendered payload must satisfy the text exposition format."""

    def test_default_render_is_well_formed(self, mod):
        declared, errors = parse_exposition(mod.render_prometheus())
        assert not errors, errors
        assert "odoo_up" in declared

    def test_pool_counters_are_typed_as_counters(self, mod, pooled_db):
        health = {
            "read_write": {
                "mode": "read/write",
                "pool": {
                    "borrows": 12,
                    "borrows_failed": 1,
                    "borrow_wait_seconds_total": 0.5,
                    "borrow_wait_seconds_max": 0.25,
                    "borrow_wait_seconds": {"le_0.001": 10, "le_+Inf": 12},
                    "budget_maxconn": 64,
                    "budget_in_use": 3,
                    "budget_exhausted": 0,
                    "pools": 2,
                },
                "per_database": {"prod": {"pool_size": 5, "requests_waiting": 0}},
            }
        }
        with patch.object(pooled_db, "pool_health", return_value=health):
            text = mod.render_prometheus()
        declared, errors = parse_exposition(text)
        assert not errors, errors
        pid = os.getpid()
        assert declared["odoo_pool_borrows_total"] == "counter"
        assert declared["odoo_pool_budget_maxconn"] == "gauge"
        assert (
            f'odoo_pool_borrow_wait_seconds_bucket{{pid="{pid}",pool="read_write",'
            'le="+Inf"} 12' in text
        )
        assert (
            f'odoo_db_pool_pool_size{{pid="{pid}",pool="read_write",database="prod"}} 5'
            in text
        )

    def test_database_names_are_escaped_in_labels(self, mod, pooled_db):
        """A label value is attacker-influenced: database names are user-chosen."""
        health = {
            "read_write": {
                "pool": {"borrows": 1},
                "per_database": {'we"ird\\name': {"pool_size": 1}},
            }
        }
        with patch.object(pooled_db, "pool_health", return_value=health):
            text = mod.render_prometheus()
        _, errors = parse_exposition(text)
        assert not errors, errors
        assert r'database="we\"ird\\name"' in text

    def test_non_numeric_per_database_stats_are_dropped(self, mod, pooled_db):
        """``pool_health`` forwards whatever the driver reports, and
        ``psycopg_pool`` mixes strings and booleans in with the numbers.

        A Prometheus sample value must be a number: emitting ``prod`` or
        ``True`` makes the whole scrape unparseable, so one new key in a
        dependency's stats dict would take the endpoint down rather than add a
        useless series.  Booleans need naming separately from "not a number" —
        ``bool`` is a subclass of ``int``, so an ``isinstance(value, int)``
        check alone lets ``True`` through.
        """
        health = {
            "read_write": {
                "pool": {"borrows": 1},
                "per_database": {
                    "prod": {
                        "pool_size": 5,
                        "pool_name": "read_write_prod",
                        "pool_available": True,
                        "requests_waiting": 0,
                        "wait_ms": 1.5,
                    }
                },
            }
        }
        with patch.object(pooled_db, "pool_health", return_value=health):
            text = mod.render_prometheus()

        _, errors = parse_exposition(text)
        assert not errors, f"a non-numeric stat broke the exposition: {errors}"
        assert "odoo_db_pool_pool_size" in text
        assert "odoo_db_pool_wait_ms" in text
        assert "odoo_db_pool_pool_name" not in text, "a string was emitted as a value"
        assert "odoo_db_pool_pool_available" not in text, (
            "a boolean was emitted as a value; bool is an int subclass and needs "
            "its own exclusion"
        )

    def test_booleans_render_as_one_and_zero(self, mod):
        from odoo.service import lifecycle

        server = MagicMock()
        type(server).__name__ = "PreforkServer"
        server.workers = {}
        server.workers_http = server.workers_cron = server.workers_job = {}
        server.population = 0
        server.generation = 0
        server.long_polling_pid = None
        server.pid = os.getpid()  # this process IS the master

        with patch.object(lifecycle, "server", server):
            text = mod.render_prometheus()
        assert f'odoo_long_polling_alive{{pid="{os.getpid()}"}} 0' in text
        _, errors = parse_exposition(text)
        assert not errors, errors

    def test_every_series_carries_the_serving_pid(self, mod, pooled_db):
        """Under prefork a scrape lands on whichever worker won ``accept(2)``.

        Each worker owns its own pools and counters, so without a ``pid`` label
        one series name would carry a different worker's numbers on every
        scrape — and a monotonic counter that jumps backwards reads to
        Prometheus as a process restart.
        """
        health = {"read_write": {"pool": {"borrows": 3}, "per_database": {}}}
        with patch.object(pooled_db, "pool_health", return_value=health):
            text = mod.render_prometheus()
        samples = [
            line for line in text.splitlines() if line and not line.startswith("#")
        ]
        assert samples
        expected = f'pid="{os.getpid()}"'
        unlabelled = [line for line in samples if expected not in line]
        assert not unlabelled, unlabelled

    def test_render_survives_a_failing_subsystem(self, mod, pooled_db):
        """A scrape that raises is a monitoring outage stacked on the incident."""
        with (
            patch.object(
                pooled_db, "pool_health", side_effect=RuntimeError("pool is gone")
            ),
            patch.object(mod, "service_metrics", side_effect=RuntimeError("no server")),
        ):
            text = mod.render_prometheus()
        assert "odoo_up 1" in text
        _, errors = parse_exposition(text)
        assert not errors, errors


class TestBorrowWaitHistogramFamily:
    """``odoo_pool_borrow_wait_seconds`` is one histogram family, not three.

    It used to be published as three independent families -- ``_sum`` and
    ``_bucket`` as counters, ``_max`` as a gauge -- with no ``_count`` sample
    and no ``# TYPE ... histogram`` line anywhere in the scrape.
    ``histogram_quantile()`` still worked off the ``le`` buckets, so the gap
    stayed invisible; what a client could not do was read the family AS a
    histogram, which is what its name promises.
    """

    HEALTH = {
        "pool": {
            "borrows": 8,
            "borrow_wait_seconds_total": 0.42,
            "borrow_wait_seconds_max": 0.19,
            "borrow_wait_seconds": {
                "le_0.001": 4,
                "le_0.01": 7,
                "le_0.1": 8,
                "le_1.0": 8,
                "le_5.0": 8,
                "le_30.0": 8,
                "le_+Inf": 8,
            },
        },
    }

    def _render(self, mod):
        exp = mod._Exposition({"pid": "1234"})
        mod._add_pool_family(exp, "read_write", self.HEALTH)
        return exp.render()

    def test_the_family_is_declared_once_as_a_histogram(self, mod):
        text = self._render(mod)
        assert "# TYPE odoo_pool_borrow_wait_seconds histogram" in text
        assert text.count("# TYPE odoo_pool_borrow_wait_seconds ") == 1
        for suffix in ("_sum", "_bucket", "_count"):
            assert f"# TYPE odoo_pool_borrow_wait_seconds{suffix} " not in text

    def test_count_is_emitted_and_equals_the_inf_bucket(self, mod):
        text = self._render(mod)
        count = [
            line
            for line in text.splitlines()
            if line.startswith("odoo_pool_borrow_wait_seconds_count")
        ]
        assert len(count) == 1
        assert count[0].endswith(" 8")
        inf = [
            line
            for line in text.splitlines()
            if 'le="+Inf"' in line and "_bucket" in line
        ]
        assert inf[0].endswith(" 8")

    def test_the_mean_wait_is_now_computable(self, mod):
        """`_sum / _count` is the whole point of a histogram family; without a
        ``_count`` sample the mean had to be reconstructed from an unrelated
        counter."""
        text = self._render(mod)
        values = {}
        for line in text.splitlines():
            for suffix in ("_sum", "_count"):
                head = f"odoo_pool_borrow_wait_seconds{suffix}"
                if line.startswith(head + "{"):
                    values[suffix] = float(line.rsplit(" ", 1)[1])
        assert values["_sum"] / values["_count"] == pytest.approx(0.0525)

    def test_max_stays_its_own_gauge_declared_before_the_histogram(self, mod):
        """``_max`` is not a histogram suffix, so it keeps its own family -- and
        must be declared before the histogram's samples start, or its TYPE line
        would land in the middle of them."""
        text = self._render(mod)
        assert "# TYPE odoo_pool_borrow_wait_seconds_max gauge" in text
        assert text.index(
            "# TYPE odoo_pool_borrow_wait_seconds_max gauge"
        ) < text.index("# TYPE odoo_pool_borrow_wait_seconds histogram")

    def test_the_whole_scrape_still_parses(self, mod):
        _, errors = parse_exposition(self._render(mod))
        assert not errors, errors

    def test_an_empty_bucket_map_still_emits_a_declared_family(self, mod):
        exp = mod._Exposition({"pid": "1234"})
        mod._add_pool_family(exp, "read_write", {"pool": {}})
        text = exp.render()
        assert "# TYPE odoo_pool_borrow_wait_seconds histogram" in text
        assert (
            'odoo_pool_borrow_wait_seconds_count{pid="1234",pool="read_write"} 0'
            in text
        )
        _, errors = parse_exposition(text)
        assert not errors, errors
