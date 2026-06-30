"""Self-contained benchmark harness for cross-version ORM comparison.

This module intentionally depends on **nothing fork-specific**.  It uses only:

* ``time.perf_counter_ns``    — wall-clock timing (portable);
* ``cursor.sql_log_count``    — SQL query counter (present and identical on both
  the fork and vanilla Odoo 19.0 — see ``BaseCase.assertQueryCount``);
* the Python standard library.

That is what makes the whole ``test_performance_compare`` module droppable into a
vanilla 19.0 checkout: there is no import of ``odoo.tests.benchmark`` (fork-only)
or of any refactored ORM internal.

Two metrics are captured for every benchmark, per the comparison plan:

* **timing**  — the headline signal (mean / median / p95 µs, with outlier
  trimming and a coefficient-of-variation stability flag);
* **queries** — a determinism guardrail (min == max means the SQL shape is
  stable; a divergence in query count between builds is flagged by ``compare.py``
  so a Python-time win that secretly costs extra round-trips cannot hide).
"""

import gc
import importlib.util
import json
import math
import os
import platform
import socket
import statistics
import time
from pathlib import Path

# Schema version of the emitted JSON, so compare.py can refuse mismatches.
REPORT_VERSION = 1

OUTLIER_PCT = 5  # trim this percentile from each tail before aggregating timing


# ---------------------------------------------------------------------------
# statistics helpers
# ---------------------------------------------------------------------------


def _percentile(sorted_data, p):
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * (p / 100)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)


def _trim_outliers(data):
    if len(data) < 20:
        return sorted(data)
    s = sorted(data)
    lo = _percentile(s, OUTLIER_PCT)
    hi = _percentile(s, 100 - OUTLIER_PCT)
    trimmed = [x for x in s if lo <= x <= hi]
    return trimmed or s


def _stats_us(times_us):
    """Reduce a list of per-iteration µs timings to summary statistics."""
    clean = _trim_outliers(times_us)
    mean = statistics.mean(clean)
    std = statistics.stdev(clean) if len(clean) > 1 else 0.0
    return {
        "mean_us": round(mean, 3),
        "median_us": round(statistics.median(clean), 3),
        "min_us": round(min(clean), 3),
        "max_us": round(max(clean), 3),
        "p95_us": round(_percentile(clean, 95), 3),
        "p99_us": round(_percentile(clean, 99), 3),
        "std_us": round(std, 3),
        "cv": round(std / mean, 4) if mean > 0 else 0.0,
        "samples": len(clean),
    }


# ---------------------------------------------------------------------------
# environment metadata
# ---------------------------------------------------------------------------


def _driver_label():
    """Best-effort name+version of the active PostgreSQL driver.

    Works across both layouts: upstream exposes the driver module as an
    attribute of ``odoo.sql_db``; the fork relocated that module, so we fall
    back to a direct probe (psycopg v3 first, since that is what the fork uses).
    """
    try:
        from odoo import sql_db

        mod = getattr(sql_db, "psycopg", None) or getattr(sql_db, "psycopg2", None)
        if mod is not None:
            name = getattr(mod, "__name__", "?")
            ver = getattr(mod, "__version__", "")
            # psycopg3's __version__ is clean; psycopg2's has trailing build info
            return f"{name} {ver.split(' ')[0]}".strip()
    except Exception:  # pragma: no cover - metadata only
        pass
    for name in ("psycopg", "psycopg2"):
        if importlib.util.find_spec(name) is None:
            continue
        ver = getattr(importlib.import_module(name), "__version__", "")
        return f"{name} {ver.split(' ')[0]}".strip()
    return "unknown"


def _odoo_version():
    try:
        import odoo.release

        return odoo.release.version
    except Exception:  # pragma: no cover - metadata only
        return "unknown"


def environment_meta():
    return {
        "label": os.environ.get("BENCH_LABEL", "unknown"),
        "python": platform.python_version(),
        "python_impl": platform.python_implementation(),
        "driver": _driver_label(),
        "odoo_version": _odoo_version(),
        "host": socket.gethostname(),
        "platform": platform.platform(),
    }


# ---------------------------------------------------------------------------
# recorder
# ---------------------------------------------------------------------------


class BenchmarkRecorder:
    """Accumulates benchmark results and writes a single labelled JSON report.

    A recorder is keyed only by *stable* benchmark names; no timestamps or other
    nondeterministic values leak into the comparison keys (the timestamp lives in
    the report header, not in the per-benchmark records), so two reports always
    line up by name.
    """

    # default iteration budget; override per-call or globally via BENCH_ITER
    DEFAULT_ITERATIONS = int(os.environ.get("BENCH_ITER", "60"))
    DEFAULT_WARMUP = int(os.environ.get("BENCH_WARMUP", "8"))

    def __init__(self, cr, logger=None):
        self.cr = cr
        self.logger = logger
        self.results = []

    def _log(self, msg, *args):
        if self.logger is not None:
            self.logger.info(msg, *args)

    def measure(
        self,
        name,
        func,
        *,
        group="",
        iterations=None,
        warmup=None,
        setup=None,
        invalidate=None,
    ):
        """Time ``func`` and record timing + query-count statistics.

        Parameters
        ----------
        name : str
            Stable benchmark identifier (the comparison key).
        func : callable
            Zero-argument callable to measure.
        group : str
            Logical grouping for reporting (e.g. "read", "write", "search").
        iterations, warmup : int
            Measured / discarded iteration counts.
        setup : callable | None
            Called before each iteration (timed out), e.g. to (re)create a row.
        invalidate : callable | None
            Called before each iteration (timed out), e.g. ``env.invalidate_all``.
        """
        iterations = iterations or self.DEFAULT_ITERATIONS
        warmup = self.DEFAULT_WARMUP if warmup is None else warmup
        cr = self.cr

        times_us = []
        q_counts = []
        gc_was_enabled = gc.isenabled()

        # Collect once up front, then keep GC disabled for the whole measured
        # loop.  A per-iteration ``gc.collect()`` evicts the CPU instruction/data
        # caches before every timed call, so it measures the *cold-cache* cost of
        # the operation — for µs-scale ORM ops that is ~8x the warm cost and is
        # dominated by code/heap footprint (e.g. how many modules are installed)
        # rather than the operation itself, which unfairly penalises a larger
        # deployment.  Collecting once and disabling for the loop measures warm
        # steady-state: lower variance and deployment-independent (the standard
        # ``timeit``/``pyperf`` approach).
        gc.collect()
        gc.disable()
        try:
            for i in range(warmup + iterations):
                if setup is not None:
                    setup()
                if invalidate is not None:
                    invalidate()
                q0 = cr.sql_log_count
                t0 = time.perf_counter_ns()
                func()
                t1 = time.perf_counter_ns()
                q1 = cr.sql_log_count
                if i >= warmup:
                    times_us.append((t1 - t0) / 1000.0)
                    q_counts.append(q1 - q0)
        finally:
            if gc_was_enabled:
                gc.enable()

        record = {"name": name, "group": group, "iterations": iterations}
        record.update(_stats_us(times_us))
        record["query_min"] = min(q_counts) if q_counts else 0
        record["query_max"] = max(q_counts) if q_counts else 0
        record["query_mean"] = (
            round(statistics.mean(q_counts), 2) if q_counts else 0.0
        )
        self.results.append(record)
        self._log(
            "[PERF_CMP] %-38s mean=%9.1fµs  p95=%9.1fµs  cv=%.2f  q=%d",
            name[:38],
            record["mean_us"],
            record["p95_us"],
            record["cv"],
            record["query_max"],
        )
        return record

    # -- output ---------------------------------------------------------------

    def report(self, timestamp):
        """Build the full report dict.  ``timestamp`` is supplied by the caller
        (tests cannot rely on a wall clock for determinism, but the header is
        purely informational and never part of a comparison key)."""
        meta = environment_meta()
        meta["timestamp"] = timestamp
        meta["report_version"] = REPORT_VERSION
        meta["benchmark_count"] = len(self.results)
        return {"meta": meta, "results": self.results}

    def write(self, timestamp):
        """Write the report to ``$BENCH_OUT`` (or ``./perf_compare_<label>.json``)
        and return the path."""
        report = self.report(timestamp)
        label = report["meta"]["label"]
        out = os.environ.get("BENCH_OUT")
        path = (Path(out) if out else Path.cwd() / f"perf_compare_{label}.json").resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
        self._log("[PERF_CMP] wrote %d results -> %s", len(self.results), path)
        return str(path)
