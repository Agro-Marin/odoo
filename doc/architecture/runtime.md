# Runtime view — what runs, when, and in how many processes

> One of the views indexed by [`ARCHITECTURE.md`](ARCHITECTURE.md).
> This view answers *what happens at run time*. For *where code lives and what it
> may import*, see [`module.md`](module.md).

The module view is a claim about source. This one is a claim about processes,
threads, cursors and order — none of which an import graph can express, and most
of which no structural gate can see. Where a claim here is proved by a running
test rather than by a checker, the test is named.

## Lifecycles

Four runtime paths a reader has to hold to debug the core. Each is a sketch;
where a canonical unflattened version exists it is named.

### Process boot

```
odoo-bin
└─ odoo.cli.main()                     cli/command.py — bootstrap parse, pick command
   └─ <Command>.run(args)              cli/server.py for the default `server` command
      └─ service.lifecycle.start()
         ├─ load_server_wide_modules()
         ├─ choose EventServer | PreforkServer | ThreadedServer
         └─ server.run(preload, stop)
            └─ service.lifecycle.preload_registries(dbnames)
               └─ Registry.new(db, update_module=…)      one registry per database
```

Before any of that, importing `odoo.orm`, `odoo.modules` or `odoo.cli.command`
executes **`odoo/init.py`**, the framework bootstrap, in this order:

| # | Step | Fails how |
|---|---|---|
| 1 | enforce `MIN_PY_VERSION` | `SystemExit` naming the required version |
| 2 | import the mandatory `odoo_rust` native extension | a hard, explained error — there is no pure-Python fallback |
| 3 | compare `odoo_rust.__source_crc__` against the crate on disk (`odoo/libs/native.py`) | refuses to start when the built extension is **stale**, naming the rebuild command. Skipped when the crate directory is absent (an installed wheel) or `ODOO_SKIP_RUST_FRESHNESS_CHECK` is set. The sibling `odoo_lint` extension is checked the same way, but at *its* import site in `odoo/libs/lint/scan.py` — it is not a runtime dependency and a server that never runs a lint gate never loads it |
| 4 | retune the GC threshold set | — |
| 5 | `_monkeypatches.patch_init()` | anything that must be patched before third-party modules load has to run from here |

Step 3 is a separate failure from step 2 and the less obvious one: a stale
extension imports cleanly and then segfaults on a cyclic `fast_clone` and
mis-orders timezone-aware columns, neither of which names its cause. CI never
sees it — every lane builds the extension fresh — so it is a long-lived
virtualenv problem only.

The other runtime floor is enforced later and by a different subsystem:
`db/pool.py` compares the server against `MIN_PG_VERSION` at connect time and
raises `PoolError`. Both constants live in `odoo/release.py` and are named here
rather than restated — a floor written into prose is a second copy that drifts.

| Config | Server | Concurrency |
|---|---|---|
| `workers = 0` (default) | `ThreadedServer` | Python threads, one process, debugger-friendly |
| `workers > 0` | `PreforkServer` | forked OS processes, no shared memory |
| `odoo.evented` | `EventServer` | gevent greenlets, one process |

All three end in the same `preload_registries` → `Registry.new` path. The choice
is not a deployment knob: a large part of the ORM's runtime design exists
*because* `workers > 0` is supported.

### Concurrency, and why the process model is architectural

With one process, a registry is an ordinary Python object and invalidating it is
an attribute write. With `workers > 0` there are N processes that share no
memory, each holding its own `Registry` per database, and **a model change made
in worker A is invisible to worker B**. There is no shared-memory channel, and
adding one would put a second coordination system beside the one the framework
already depends on. So the framework coordinates through the database.

`orm/runtime/registry.py` implements it as a sequence protocol over ordinary
tables (`orm_signaling_registry`, plus one per cache key in `CACHES_BY_KEY`),
each holding nothing but a `SERIAL` id and a timestamp:

| Operation | Mechanism | Why this way |
|---|---|---|
| **Publishing** | `Registry.signal_changes()` `INSERT`s a row and reads back **the id the database generated** (`RETURNING id`) | not `local + 1`: concurrent inserts are the normal case, so two workers signalling together take ids N+1 and N+2 while both would record `+= 1` locally, and the loser would see `db > local` and pay a full `Registry.new()` — the most expensive operation in the system — to learn about a change it made itself |
| **Observing** | `Registry.check_signaling()` reads `max(id)` per table against what this process last saw | a **registry** sequence ahead means the model classes are stale: adopt an already-published newer registry if one exists, else drain the pool and call `Registry.new()`. A **cache** sequence ahead clears only the LRUs behind that key, which is why eviction costs far less than a rebuild and why the two use separate tables |
| **Tolerating lag** | a sequence *below* the local one is logged and ignored as stale | signaling may be read through a read-only cursor that lands on a replica, and a replica behind the primary must not thrash every worker's registry |

Three consequences for code anywhere in the core:

- **A registry is per `(process, database)`, never global.** Anything attached to
  one is invisible to the other workers until something signals.
- **A process-lifetime cache must be registered in `CACHES_BY_KEY`**, or it
  serves stale values in every worker but the one that changed the data — and no
  test with `workers = 0` can reproduce it.
- **`Registry.new()` can run more than once per process**, and not only at boot:
  a signaling check triggers it, and so does `_UninstallRequiresReload` from
  inside `load_modules`. Code that assumes one registry build per process start
  is wrong.

The cron runner is the same argument in a second place. `service/_threaded.py`
and `service/_worker.py` reach `IrCron._process_jobs` / `IrJob._process_jobs`
directly — the two pinned `core-does-not-depend-on-addons` exceptions —
because a cron thread runs *before* a registry exists for that database and has
no `env` to route through. The exception is a consequence of the process model,
not an oversight.

### Registry build

`Registry.new()` is the most expensive operation in the system and the only way
a database's model classes come into existence. It refuses to run against a
system or template database, allocates the registry, sets up cross-process
signalling, then hands off to `modules.loading.load_modules()`, whose phases are
methods on `_ModuleLoader`:

```
Registry.new(db)
├─ setup_signaling()                      cross-process registry/cache sequences
└─ load_modules(registry, …)
   ├─ bootstrap()                         `base` present? graph seeded?
   ├─ run_pre_upgrade_scripts()           update only
   ├─ capture_database_field_metadata()   update only, before the schema moves
   ├─ open_environment_and_load_base()    first Environment; `base` data loaded
   ├─ load_languages()
   ├─ process_module_requests()           update only: to-install / to-upgrade
   ├─ converge_module_graph()             load modules until the graph is stable
   ├─ finish_registry_setup()             _setup_models__ / init_models
   ├─ run_end_migrations()                update only
   ├─ finalize_constraints()              deferred constraints, then NOT NULL
   ├─ uninstall_removed_modules()         update only; may force one full reload
   ├─ validate_custom_views()             update only
   └─ register_model_hooks() · check_null_constraints()
```

Fourteen of the 22 calls, in call order; the sketch selects, it does not
enumerate. [`scenarios.md`](scenarios.md#scenario-a--installing-a-module)
selects thirteen for a different purpose, so the two lists differ — read either
as an ordering claim, never as the full sequence, which is `loading.py`'s.

Two consequences before touching this path:

- **The graph is iterated by phase, then dependency depth, then name** — never by
  filesystem order. A module's data loads only after every dependency's.
- **`uninstall_removed_modules()` can raise `_UninstallRequiresReload`**, which
  makes `load_modules` call `Registry.new()` again from inside itself.

After `load_modules` returns, `Registry.new` marks the registry ready, calls
`_ensure_field_triggers()`, and `signal_changes()` so other workers reload.

### Request lifecycle (HTTP)

```
WSGI  →  Application.__call__  →  Request (_post_init: session + db)
      →  _serve_static | _serve_nodb | _serve_db
            _serve_db: registry cursor → Environment → ir.http._match
                match  → service.transaction.retrying(_serve_ir_http):
                             ir.http._authenticate → ir.http._pre_dispatch
                             → Dispatcher.pre_dispatch → Dispatcher.dispatch
                             (→ ir.http._dispatch → endpoint)
                             → ir.http._post_dispatch
                no match → retrying(_serve_ir_http_fallback):
                             ir.http._serve_fallback → ir.http._post_dispatch
            → cr.close() → response
```

Three details the sketch flattens, all claims about **order**:

- **`retrying()` lives in `odoo/service/transaction.py`**, not on a model. It
  re-runs the callable on PostgreSQL serialization/deadlock errors, rewinding
  uploaded files between attempts.
- **Commit and session-save both happen *inside* the sketch, not after it.**
  `env.cr.commit()` is the last thing `retrying()` does once its callable
  returns, and the session is written earlier still — by
  `Dispatcher.post_dispatch` → `Request._save_session()`, so *before* that
  commit. `_serve_db` itself only closes the cursor, in its `finally`.
- **RO → RW promotion.** A route declared `readonly` first runs on a read-only
  cursor. If its handler writes, `psycopg.errors.ReadOnlySqlTransaction` is
  caught, a read/write cursor is acquired and **the handler runs a second time**
  — so non-transactional side effects (emails, outbound calls) must not precede
  the first write.

No text search can settle an ordering claim: every gate that "covers" the three
above is a grep, and a commit moving the commit above the dispatcher call would
satisfy all of them. The runtime proof is
`addons/test_http/tests/test_lifecycle_order.py`, which patches
`Request._save_session` and *both* cursor classes and reads the sequence off the
serving thread. Observed: `[save_session, commit]` normally, and
`[save_session, save_session, commit]` on the promoted path. (Both cursor
classes, because under `HttpCase` the request's `env.cr` is a `TestCursor`,
which subclasses `BaseCursor` rather than `Cursor`; instrumenting `Cursor.commit`
alone observes nothing and reads as "`retrying()` never commits".)

`Dispatcher` has three subclasses (`HttpDispatcher`, `JsonRPCDispatcher`,
`Json2Dispatcher`) selected by `routing["type"]`.

The canonical, unflattened call graph — every stage and what each is responsible
for — is **`odoo/http/README.md`**, which also carries `http/`'s module map,
gated by `package_index_check.py`.

### Transaction, cache and flush

One `Transaction` per cursor (`cr.transaction`), created lazily by the first
`Environment` built on that cursor. It owns the registry reference and the
per-transaction machinery:

```
Cursor ──── transaction ────┬─ registry          the model classes
                            ├─ _cache_store      FieldCache   (field values, dirty ids)
                            ├─ _compute_engine   ComputeEngine (pending recomputes)
                            ├─ core              OrmCore  ← the curated facade, env._core
                            ├─ unit_of_work      UnitOfWork (the fixpoint loops)
                            ├─ backend           PostgresBackend · InMemoryBackend = DB-free
                            └─ envs              interned Environments
```

`Environment(cr, uid, context, su)` is **interned** per `(cr, uid, su, context)`:
constructing one with the same key returns the existing object. Environments are
cheap and identity-comparable, and any per-request state must live on the
transaction or the request, never on an `Environment` you happen to hold.

**Writes do not reach SQL where you write them.** `create()`/`write()` update the
field cache, mark ids dirty, and schedule dependent computes; the database sees
no write until a flush. A flush is a *fixpoint loop*, because recomputing one
field can dirty another:

```
env.flush_all()
└─ UnitOfWork.run_flush_loop(recompute_fn, flush_fn)     ≤ MAX_FIXPOINT_ITERATIONS (1000)
   ├─ recompute_fn(field)  → model._recompute_field(field)
   └─ flush_fn(models)     → model.flush_model()   inside one cr.pipeline()
                              ├─ _recompute_fields(stored computed fields)
                              └─ _flush()  pops the dirty ids → UPDATE
```

Non-convergence is an error, not a warning: the loop raises unless the context
carries `tolerant_recompute`, and `UnitOfWork` carries a stall detector so a loop
that stops making progress fails in seconds instead of grinding to the cap.
`flush_model()` / `flush_recordset()` are the scoped versions and both
short-circuit when nothing is pending or dirty.

The loop still issues *reads*: prefetch `SELECT`s land where the field is first
touched. Measured, a 10,000-record write loop issues 20 statements before the
flush and 100 at it ([`qualities.md`](qualities.md#scenario-1--write-throughput)).

Row I/O at the bottom goes through `env.backend`, the ADR-0011 port described
under **Seams** — which is what lets the whole ORM run against `InMemoryBackend`
with no database. **`backend` is non-optional and has two implementors**, which
is why the sketch above names one rather than leaving it unset: until 2026-08-08
a null `env.backend` *was* the PostgreSQL implementation, an unnamed branch at
fifteen sites.
