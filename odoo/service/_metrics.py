from __future__ import annotations

import os
import threading
from typing import Any

from odoo.modules.registry import Registry

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

#: Base name of the borrow-wait histogram family.  Its samples are
#: ``<name>_bucket`` / ``_sum`` / ``_count``; the family is declared once.
_BORROW_WAIT = "odoo_pool_borrow_wait_seconds"

_LABEL_ESCAPES = str.maketrans({"\\": "\\\\", '"': '\\"', "\n": "\\n"})


def _labels(pairs: dict[str, str]) -> str:
    if not pairs:
        return ""
    inner = ",".join(
        f'{k}="{str(v).translate(_LABEL_ESCAPES)}"' for k, v in pairs.items()
    )
    return "{" + inner + "}"


class _Exposition:
    def __init__(self, base_labels: dict[str, str] | None = None) -> None:
        self._lines: list[str] = []
        self._declared: set[str] = set()
        self._base = dict(base_labels or {})

    def declare(self, name: str, kind: str, help: str = "") -> None:
        """Declare a family whose samples carry a suffix.

        A Prometheus histogram is ONE family -- one HELP, one TYPE -- exposed
        through ``_bucket`` / ``_sum`` / ``_count`` samples.  Declaring each
        suffix as its own family (two counters and a gauge, which is what this
        module used to publish) yields something no client reads as a histogram:
        the quantile functions still work off the ``le`` buckets, but the family
        has no declared type and the mean has no ``_count`` to divide by.
        """
        if name in self._declared:
            return
        self._declared.add(name)
        self._lines.append(f"# HELP {name} {help}")
        self._lines.append(f"# TYPE {name} {kind}")

    def sample(
        self,
        name: str,
        value: float | bool,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Emit a sample of an already-declared family, with no TYPE of its own."""
        rendered = int(value) if isinstance(value, bool) else value
        self._lines.append(f"{name}{_labels(self._base | (labels or {}))} {rendered}")

    def add(
        self,
        name: str,
        value: float | bool,
        *,
        kind: str = "gauge",
        help: str = "",
        labels: dict[str, str] | None = None,
    ) -> None:
        self.declare(name, kind, help)
        self.sample(name, value, labels=labels)

    def render(self) -> str:
        return "\n".join(self._lines) + "\n"


def service_metrics() -> dict[str, Any]:
    from . import lifecycle

    server = lifecycle.server
    out: dict[str, Any] = {
        "flavor": "none",
        "registries": len(Registry.registries),
    }
    if server is None:
        return out

    out["flavor"] = {
        "PreforkServer": "prefork",
        "ThreadedServer": "threaded",
        "EventServer": "evented",
    }.get(type(server).__name__, type(server).__name__)

    if hasattr(server, "workers"):
        # Only the master knows the fleet.  A worker reached this line holding
        # the PreforkServer it inherited through os.fork() (_prefork.py:142):
        # workers_*, population, generation and long_polling_pid are all frozen
        # at the instant of that fork and never updated in the child, so each
        # worker would publish a different — and wrong — view of the fleet.
        if os.getpid() == server.pid:
            out["workers"] = {
                "http": len(server.workers_http),
                "cron": len(server.workers_cron),
                "job": len(server.workers_job),
            }
            out["worker_population"] = server.population
            out["worker_generation"] = server.generation
            out["long_polling_alive"] = server.long_polling_pid is not None
    else:
        by_type: dict[str, int] = {}
        for thread in threading.enumerate():
            kind = getattr(thread, "type", None)
            if kind in ("http", "cron", "job"):
                by_type[kind] = by_type.get(kind, 0) + 1
        out["threads"] = {k: by_type.get(k, 0) for k in ("http", "cron", "job")}
        httpd = getattr(server, "httpd", None)
        max_threads = getattr(httpd, "max_http_threads", 0) if httpd else 0
        out["http_threads_max"] = max_threads
        out["limits_reached_threads"] = len(
            getattr(server, "limits_reached_threads", ())
        )
    return out


def _add_pool_family(exp: _Exposition, mode: str, health: dict) -> None:
    counters = {
        "borrows": ("odoo_pool_borrows_total", "Connections borrowed from the pool."),
        "borrows_direct": (
            "odoo_pool_borrows_direct_total",
            "Borrows served outside the pooled path.",
        ),
        "borrows_failed": (
            "odoo_pool_borrows_failed_total",
            "Borrows that raised instead of yielding a connection.",
        ),
        "pools_created": ("odoo_pool_created_total", "Per-DSN pools created."),
        "pools_reaped": (
            "odoo_pool_reaped_total",
            "Per-DSN pools closed by the idle reaper.",
        ),
        "pools_evicted_stale": (
            "odoo_pool_evicted_stale_total",
            "Per-DSN pools evicted because their credentials changed.",
        ),
        "connections_discarded": (
            "odoo_pool_connections_discarded_total",
            "Connections dropped rather than returned to the pool.",
        ),
        "probe_run": (
            "odoo_pool_probe_run_total",
            "Pre-flight connectability probes run.",
        ),
        "probe_permanent": (
            "odoo_pool_probe_permanent_total",
            "Probes that concluded the failure was permanent.",
        ),
        "probe_transient": (
            "odoo_pool_probe_transient_total",
            "Probes that concluded the failure was transient.",
        ),
        "probe_skipped_proven": (
            "odoo_pool_probe_skipped_total",
            "Probes skipped because the DSN was already proven.",
        ),
        "budget_exhausted": (
            "odoo_pool_budget_exhausted_total",
            "Times the shared connection budget was exhausted.",
        ),
        "leaks_reported": (
            "odoo_pool_leaks_reported_total",
            "Times a connection was found held past db_leak_detection.",
        ),
    }
    gauges = {
        "pools": ("odoo_pool_pools", "Per-DSN pools currently open."),
        "direct_out": (
            "odoo_pool_direct_out",
            "Direct (unpooled) connections outstanding.",
        ),
        "budget_maxconn": (
            "odoo_pool_budget_maxconn",
            "Shared connection budget ceiling.",
        ),
        "budget_available": ("odoo_pool_budget_available", "Unclaimed budget slots."),
        "budget_in_use": ("odoo_pool_budget_in_use", "Budget slots currently held."),
        "checked_out": (
            "odoo_pool_checked_out",
            "Connections currently checked out by a borrower.",
        ),
        "checked_out_oldest_seconds": (
            "odoo_pool_checked_out_oldest_seconds",
            "Age of the longest-held checkout; a rising floor is a leak.",
        ),
    }

    stats = health.get("pool") or {}
    label = {"pool": mode}
    for key, (name, help_text) in counters.items():
        if key in stats:
            exp.add(name, stats[key], kind="counter", help=help_text, labels=label)
    for key, (name, help_text) in gauges.items():
        if key in stats:
            exp.add(name, stats[key], help=help_text, labels=label)

    if "backends" in health:
        exp.add(
            "odoo_pool_backends",
            health["backends"],
            help=(
                "Server connections held (checked out + idle). NOT bounded by "
                "db_maxconn: each per-DSN pool retains up to that many idle, "
                "so this can reach maxconn x databases."
            ),
            labels=label,
        )

    # Its own family: ``_max`` is not a histogram suffix, so it is declared
    # first, before the histogram's samples begin.
    exp.add(
        "odoo_pool_borrow_wait_seconds_max",
        stats.get("borrow_wait_seconds_max", 0.0),
        help="Longest single borrow wait observed.",
        labels=label,
    )

    buckets = stats.get("borrow_wait_seconds") or {}
    exp.declare(
        _BORROW_WAIT,
        "histogram",
        help="Time borrows spent waiting for a connection.",
    )
    for edge, count in buckets.items():
        exp.sample(
            f"{_BORROW_WAIT}_bucket",
            count,
            labels={"pool": mode, "le": edge.removeprefix("le_")},
        )
    exp.sample(
        f"{_BORROW_WAIT}_sum",
        stats.get("borrow_wait_seconds_total", 0.0),
        labels=label,
    )
    # The ``+Inf`` bucket IS the observation count, and it comes from the same
    # snapshot as the rest -- so the mean cannot skew the way it would against a
    # separately-read counter.
    exp.sample(f"{_BORROW_WAIT}_count", buckets.get("le_+Inf", 0), labels=label)

    for database, per_db in (health.get("per_database") or {}).items():
        for key, value in (per_db or {}).items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            exp.add(
                f"odoo_db_pool_{key}",
                value,
                help="psycopg_pool per-database statistic.",
                labels={"pool": mode, "database": database},
            )


def render_prometheus() -> str:
    from odoo import db

    exp = _Exposition({"pid": str(os.getpid())})
    exp.add("odoo_up", 1, help="1 when the metrics endpoint is serving.")

    try:
        svc = service_metrics()
    except Exception:
        svc = {}
    if svc:
        exp.add(
            "odoo_server_info",
            1,
            help="Server flavor, as a label on a constant 1.",
            labels={"flavor": svc.get("flavor", "unknown")},
        )
        exp.add(
            "odoo_registries",
            svc.get("registries", 0),
            help="Registries held in memory.",
        )
        for kind, count in (svc.get("workers") or {}).items():
            exp.add(
                "odoo_workers",
                count,
                help="Live prefork worker processes.",
                labels={"type": kind},
            )
        for kind, count in (svc.get("threads") or {}).items():
            exp.add(
                "odoo_threads",
                count,
                help="Live service threads.",
                labels={"type": kind},
            )
        for key, name, help_text in (
            (
                "worker_population",
                "odoo_worker_population",
                "Configured HTTP worker count.",
            ),
            (
                "worker_generation",
                "odoo_worker_generation",
                "Workers forked since start.",
            ),
            (
                "http_threads_max",
                "odoo_http_threads_max",
                "Bounded HTTP handler slots.",
            ),
            (
                "limits_reached_threads",
                "odoo_limits_reached_threads",
                "Threads over their time limit, pending recycle.",
            ),
            (
                "long_polling_alive",
                "odoo_long_polling_alive",
                "1 when the evented subprocess is running.",
            ),
        ):
            if key in svc:
                exp.add(name, svc[key], help=help_text)

    try:
        pools = db.pool_health()
    except Exception:
        pools = {}
    for mode, health in (pools or {}).items():
        if health:
            _add_pool_family(exp, mode, health)

    return exp.render()


__all__ = ("CONTENT_TYPE", "render_prometheus", "service_metrics")
