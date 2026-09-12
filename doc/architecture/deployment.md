# Deployment view — what runs where, and how it degrades

> One of the views indexed by [`ARCHITECTURE.md`](ARCHITECTURE.md).
> The runtime view describes what happens *inside* one process. This one
> describes **how many processes there are, what each is allowed to do, and what
> happens when one stops being healthy.**

The framework ships three deployment shapes, chosen at startup by two config
values. They differ in ways that reach the architecture rather than the ops
runbook — most of all in whether memory is shared.

## Choosing the shape

`service/_factory.py::start` picks the server, in this order:

| Condition | Server | Concurrency | Shared memory |
|---|---|---|---|
| `odoo.evented` | `EventServer` | gevent greenlets | one process |
| `workers > 0` | `PreforkServer` | forked OS processes | **none** |
| otherwise (default) | `ThreadedServer` | Python threads | one process |

The default is `workers = 0` — threaded, one process, debugger-friendly, and the
shape every measurement in [`qualities.md`](qualities.md) was taken under. The
threaded path additionally calls `_limit_malloc_arenas()`, which the forked path
does not need.

**The choice between threaded and prefork is architectural, not operational.**
Under `workers > 0` there is no shared memory, so every registry and every cache
exists once *per worker*, and a change made in one is invisible to the others
until it travels through PostgreSQL — see the signalling tables in
[`data.md`](data.md#2-the-signalling-tables--cross-process-coordination). Code
that is correct threaded and wrong prefork is code that assumed one process.

## The prefork worker mix

`PreforkServer` maintains three worker populations, not one:

| Worker | How many | Serves |
|---|---|---|
| `WorkerHTTP` | `workers` (the `population`) | HTTP requests |
| `WorkerCron` | `max_cron_threads` (default **2**) | scheduled jobs |
| `WorkerJob` | its own pool | queued jobs |

`--workers 4` does **not** mean four processes: four HTTP workers *plus* the
cron and job populations, each sized independently. The three populations are
sized separately and **timed separately too**: the table below carries a
per-job wall-time knob and two worker-lifetime knobs beside the cron ones, each
defaulting to *defer to the tier above it* rather than to a number, so a
deployment that tunes only `limit_time_real` has silently tuned all three. The
listen backlog is `8 * population`, and `SIGTTIN` / `SIGTTOU` move the
population up and down at runtime.

Cron workers hold registries and database connections exactly like an HTTP
worker, so they count against `db_maxconn` and against the per-registry memory
measured in [`qualities.md`](qualities.md#scenario-3--multi-tenancy-cost).

### Reload and worker retirement

Prefork reload keeps the original master as a stable supervisor. A replacement
inherits the listening socket, preloads its registries, and waits for its workers
to report startup completion before acknowledging readiness over an owned pipe.
An ordinary watchdog heartbeat during a listener reconnect is not that signal.
Failed preload or a readiness timeout discards the replacement and keeps the
current generation supervised and serving. Successful promotion drains the old
workers; later reload requests return to the original supervisor, avoiding a
growing chain of proxy masters. The stable supervisor owns the file watcher so
an edit does not schedule duplicate reloads. The replacement rereads configuration normally.

The evented process restarts with its generation; this handoff does not preserve
established WebSocket connections. Shutdown bounds generation draining and kills
remaining descendants in its owned process group after the generation exits.
`tests/process/test_reload_continuity.py` covers served requests during successful
reload and preservation of the current generation after rejected replacements.

SIGTTOU initiates graceful retirement of excess HTTP workers. Retiring workers
remain in the watchdog and reaping registries until exit, and are not signaled
repeatedly on subsequent supervision passes. A failed initial preload also
returns a failing exit status in serving mode, for both threaded and prefork
servers, before starting cron and job workers.

## The limits that end a request or a worker

Defaults, from `odoo/tools/config.py`:

| Knob | Default | Bounds |
|---|---|---|
| `workers` | `0` | HTTP worker processes; `0` selects threaded |
| `max_cron_threads` | `2` | cron workers |
| `limit_request` | `65536` | requests a worker serves before it is recycled |
| `limit_memory_soft` | `2048 MB` | RSS above this stops the worker *after* the current request; the only memory limit the process enforces |
| `limit_memory_soft_gevent` | `None` | overrides `limit_memory_soft` on the `EventServer` path only |
| `limit_memory_hard` | `2560 MB` | **deprecated, enforced by nothing in-process** — see below |
| `limit_memory_hard_gevent` | `None` | the `EventServer` twin of the row above, and enforced by nothing for the same reason |
| `limit_time_cpu` | `60 s` | CPU time per request |
| `limit_time_real` | `120 s` | wall time per request |
| `limit_time_real_cron` | `-1` | wall time per cron job; `-1` defers to `limit_time_real` |
| `limit_time_real_job` | `-1` | wall time per background job; `-1` defers to `limit_time_real_cron`, which defers in turn |
| `limit_time_worker_cron` | `0` | how long a cron thread or worker lives before it is restarted; `0` disables |
| `limit_time_worker_job` | `-1` | the same for a job worker; `-1` defers to `limit_time_worker_cron` |
| `db_maxconn` | `64` | checked-out connections, **per PostgreSQL server** |

**There is one memory limit, not one of four.** `limit_memory_soft` is enforced at
three sites — `_worker.py`'s `check_limits`, and `_threaded.py` for the HTTP and
gevent paths — each calling `get_memory_over_soft_limit()` (`_limits.py`) on the
process's RSS and, above it, clearing `alive` so the worker stops after the
current request. A fourth site reads the value for an unrelated purpose:
`lifecycle.py::_limit_resident_registries` divides it by the average registry
size to bound how many registries are held at once.

`limit_memory_hard` is read **nowhere in `odoo/service/`**. There is no
in-process `RLIMIT_AS`: the allocator and gevent reserve multi-GB of
never-resident virtual address space, which that rlimit counts and RSS does
not. `config.py`'s help says "Deprecated/not enforced in-process" and directs
the hard cap to a cgroup v2 limit on the systemd unit (`MemoryMax=` with
`MemorySwapMax=0`).

A deployment sized on the 512 MB between the two has **no** hard ceiling unless
the unit file supplies one: past the soft limit a worker finishes its request and
exits, and a single request that allocates without bound is bounded by the OOM
killer, not by Odoo. A number that reads as a guarantee because it has a default and a row in a
table.

A deployment whose steady-state RSS is near the soft limit recycles constantly
and pays a registry rebuild each time. `limit_request` exists because a
long-lived Python process accumulates; recycling is the design, not a workaround.

## Degradation — the `db/` resilience tier

| Module | Handles |
|---|---|
| `budget.py` | `ConnectionBudget` — the shared `db_maxconn` cap, its permit semaphore, its saturation counter |
| `breaker.py` | `CircuitBreaker` — failure gating with exponential backoff for an optional endpoint (the read replica) |
| `lag.py` | `ReplicaLagGate` + `LAG_SQL` — a sampled apply-lag ceiling that **demotes stale reads to the primary** |
| `reaper.py` | `IdlePoolReaper` — which quiet per-DSN pools to close, and how often to look |
| `probe.py` | `ReachabilityProbe` — is this DSN connectable, and **permanently or not**: a pre-flight connect that turns a missing database or a rejected password into a millisecond error instead of a `PoolTimeout` at the end of the borrow budget, plus the per-key proof that stops it re-asking |
| `leaks.py` | `CheckoutTracker` — which connections are out, since when, from which thread and borrow site |
| `metrics.py` | `_MetricsMixin` — the per-cursor SQL counters (`sql_from_log`, `sql_into_log`, `sql_log_count`), so a slow request can name its statements rather than report a total |
| `stats.py` | `PoolStats` — the counters behind `ConnectionPool.get_health()`: borrows, failures, and a bucketed borrow-wait histogram, each written under one lock because `x += 1` lost increments in exactly the concurrency they exist to diagnose |

**Five of the eight act and three only observe**: `breaker`, `lag`, `budget`,
`reaper` and `probe` change what a request gets, while `leaks`, `metrics` and
`stats` only say what happened — and the observers are what a capacity
decision is made from. The tier is `db-resilience-below-connectivity`'s
source list ([`module.md`](module.md#dependency-rules)).

Two properties for any capacity decision:

**The budget is per PostgreSQL server, not per process or per database.**
`db_maxconn` caps a *server's* checked-out connections (`db/endpoints.py` keys
the budget by endpoint): a budget per database over-commits the server, and a
single budget across two independent servers under-uses both.

**The replica is optional and self-demoting.** Lag is sampled, and reads that
would be too stale go to the primary instead of being served wrong. The breaker
backs off exponentially to a ceiling of `REPLICA_RETRY_TIME` (1200 s),
which the table above does not list because it is not the resilience tier's:
`db/breaker.py` owns the `CircuitBreaker`, and `db/replica.py` — connectivity,
since it holds the two connections — owns the constant and constructs the
breaker with it inside the `ReplicaRouter` that `Registry.cursor` delegates
to. The ceiling is the maximum a doubling backoff reaches, so a blip recovers
in about a second while the worst case is twenty minutes.

## What a deployment must provide

| Dependency | Why it is not optional |
|---|---|
| **PostgreSQL** | every cross-process signal travels through it; `MIN_PG_VERSION` (`odoo/release.py`) is 18 and `db/pool.py` refuses older servers |
| **The filestore** | attachment bytes; must be backed up *with* the database ([`data.md`](data.md#the-dual-storage-seam)) |
| **Addons on disk** | `addons_path`; earlier entries shadow later ones |
| **`odoo_rust`** | imported at startup; absent, the process warns and runs on the pure-Python twins behind `odoo/libs/accel.py` unless `ODOO_REQUIRE_NATIVE` or `CI` makes its absence fatal. A *stale* or *debug* build is always fatal. `odoo_lint`, the sibling extension carrying the `test_lint` source scanner, is **not** a deployment dependency: it is a separate wheel that only the lint gates import |

## What this view does not cover

- **The reverse proxy.** `proxy_mode`, TLS termination, and what the deployment
  in front of Odoo must set are not described here.
- **Measured behaviour under `workers > 0`.** Every figure in
  [`qualities.md`](qualities.md) is single-process; the prefork path's latency,
  memory and signalling cost are unmeasured.
- **Cron contention across workers.** How `max_cron_threads` workers avoid
  running the same job is a runtime concern, not described in this view.
- **Database migrations during rolling upgrades.** Keeping a healthy generation
  running after a rejected replacement does not undo committed schema changes.
