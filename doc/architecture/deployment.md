# Deployment view — what runs where, and how it degrades

> One of the views indexed by [`ARCHITECTURE.md`](ARCHITECTURE.md).
> The runtime view describes what happens *inside* one process. This one
> describes **how many processes there are, what each is allowed to do, and what
> happens when one stops being healthy.**

The framework ships three deployment shapes, chosen at startup by two config
values. They differ in ways that reach the architecture rather than the ops
runbook — most of all in whether memory is shared.

## Choosing the shape

`service/lifecycle.py::start` picks the server, in this order:

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
cron and job populations, each sized independently. The listen backlog is
`8 * population`, and the population can be adjusted at runtime
(`self.population += 1`).

Cron workers hold registries and database connections exactly like an HTTP
worker, so they count against `db_maxconn` and against the per-registry memory
measured in [`qualities.md`](qualities.md#scenario-3--multi-tenancy-cost).

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
| `limit_time_cpu` | `60 s` | CPU time per request |
| `limit_time_real` | `120 s` | wall time per request |
| `limit_time_real_cron` | `-1` | wall time per cron job; `-1` defers to `limit_time_real` |
| `db_maxconn` | `64` | checked-out connections, **per PostgreSQL server** |

**There is one memory limit, not a pair.** `limit_memory_soft` is enforced at
three sites — `_worker.py`'s `check_limits`, and `_threaded.py` for the HTTP and
gevent paths — each calling `over_memory_soft_limit()` on the process's RSS and,
above it, clearing `alive` so the worker stops after the current request. A
fourth site reads the value for an unrelated purpose: `lifecycle.py` divides it
by the average registry size to bound how many registries are held at once.

`limit_memory_hard` is read **nowhere in `odoo/service/`**. The in-process
`RLIMIT_AS` that once enforced it was removed because the allocator and gevent
reserve multi-GB of never-resident virtual address space, which that rlimit
counts and RSS does not; `config.py`'s help says "Deprecated/not enforced
in-process" and directs the hard cap to a cgroup v2 limit on the systemd unit
(`MemoryMax=` with `MemorySwapMax=0`).

A deployment sized on the 512 MB between the two has **no** hard ceiling unless
the unit file supplies one: past the soft limit a worker finishes its request and
exits, and a single request that allocates without bound is bounded by the OOM
killer, not by Odoo. It is the sharpest example on these pages of a number that
reads as a guarantee because it has a default and a row in a table.

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
| `leaks.py` | `CheckoutTracker` — which connections are out, since when, from which thread and borrow site |

Two properties for any capacity decision:

**The budget is per PostgreSQL server, not per process or per database.**
`db_maxconn` caps a *server's* checked-out connections; `odoo/db/README.md`
records that this has been mis-keyed in both directions historically — a budget
per database over-committed the server, and a single budget across two
independent servers under-used both.

**The replica is optional and self-demoting.** Lag is sampled, and reads that
would be too stale go to the primary instead of being served wrong. The breaker
backs off exponentially to a ceiling of `_REPLICA_RETRY_TIME` (20 minutes),
which the table above does not list because it is not `db/`'s: `db/breaker.py`
owns the `CircuitBreaker`, `orm/runtime/registry.py` owns the constant and
constructs the breaker with it. It was previously a *flat* 20-minute window, so
a single transient failure cost 20 minutes of full primary load with nothing
re-checking; it is now the maximum a doubling backoff reaches, so a blip recovers
in about a second while the worst case is unchanged.

## What a deployment must provide

| Dependency | Why it is not optional |
|---|---|
| **PostgreSQL** | every cross-process signal travels through it; CI runs 18 |
| **The filestore** | attachment bytes; must be backed up *with* the database ([`data.md`](data.md#the-dual-storage-seam)) |
| **Addons on disk** | `addons_path`; earlier entries shadow later ones |
| **`odoo_rust`** | imported unconditionally at startup — no pure-Python fallback. `odoo_lint`, the sibling extension carrying the `test_lint` source scanner, is **not** a deployment dependency: it is a separate wheel that only the lint gates import |

## What this view does not cover

- **The reverse proxy.** `proxy_mode`, TLS termination, and what the deployment
  in front of Odoo must set are not described here.
- **Measured behaviour under `workers > 0`.** Every figure in
  [`qualities.md`](qualities.md) is single-process; the prefork path's latency,
  memory and signalling cost are unmeasured.
- **Cron contention across workers.** How `max_cron_threads` workers avoid
  running the same job is a runtime concern, not described in this view.
- **Rolling restarts and zero-downtime upgrade**, which interact with registry
  signalling and are not specified anywhere in this document set.
