# `odoo.db` — PostgreSQL connectivity layer

Fork-specific replacement for upstream's monolithic `sql_db.py`: psycopg 3
(server-side binding, pipeline mode) fronted by per-database
`psycopg_pool.ConnectionPool`s. Read this before editing; module docstrings
carry the detailed invariants — this file is the map.

## Module map

| Module | Contents | Pure? |
|---|---|---|
| `__init__.py` | Public API: `db_connect`, `close_db`/`close_all`, `drain_db`/`drain_all`, lazy process-wide R/W + read-only `ConnectionPool` pair, `sql_counter` via module `__getattr__` | no |
| `cursor.py` | `BaseCursor` (hooks, flush convergence, savepoint seam) and `Cursor` (the `cr` object: execute/executemany/pipeline, DDL handling, close/commit/rollback guards) | no |
| `pool.py` | `ConnectionBudget` (the shared `db_maxconn` cap), `ConnectionPool` (per-DSN psycopg_pool registry, borrow/give_back, idle-pool reaper, stale-credential eviction, pre-flight probe + reachability proof, direct maintenance-DB path) and `Connection` | no |
| `bulk.py` | `_BulkAccessMixin`: `copy_from` (COPY, optional binary + pre-generated ids), `execute_values` | no |
| `savepoint.py` | `Savepoint` / `_FlushingSavepoint` (ORM state restore is injected by `odoo.orm.runtime.savepoint`) | yes |
| `ddl.py` | DDL keyword detection + client-side param inlining (`$N` is rejected in DDL positions) | yes |
| `dsn.py` | DSN expansion/normalization (pool keys, password fingerprint), connect-error classification | yes |
| `errors.py` | `CURSOR_LOGGER_NAME`, retry taxonomy (`PG_RETRY_*`), user-fault taxonomy (`PG_USER_FAULT_*`), `_log_sql_error`'s three log tiers | yes |
| `lifecycle.py` | psycopg_pool `configure`/`reset`/`check` callbacks (adapters, prepare tuning, session reset, grace-windowed health check) | no |
| `schema_cache.py` | `TransactionSchemaCache`: per-cursor, transaction-lifetime catalog facts for `copy_from` (id sequences, column types) | yes |
| `metrics.py` | `_MetricsMixin` (query counters, thread metrics, DEBUG per-table stats), `sql_counter` | yes* |
| `utils.py` | `connection_info_for`, `is_maintenance_db`, `categorize_query`, `seed_planner_stats`, adapter registration | no |

“Pure” = importable and testable without a database or the framework
(`yes*`: pure logic, but pulls `odoo.tools` on import).

## Load-bearing invariants (cross-module)

- **One budget for the process**: `db_maxconn` is a `ConnectionBudget` built
  once in `__init__.py` and shared by the R/W *and* read-only pools, so it means
  what its help text says. Each pool used to own a `BoundedSemaphore(db_maxconn)`,
  making the real ceiling `2 * db_maxconn` — 128 against a stock
  `max_connections = 100`. The trade: one budget can starve itself where two
  could not (a request holding a R/W cursor while opening a read-only one), but
  `db_borrow_timeout` bounds that to a `PoolError`, whereas overshooting the
  server's limit does not degrade, it fails.
- **Budget accounting**: a permit is taken in
  `ConnectionPool.borrow`/`_borrow_direct` and travels with the connection via
  the `_odoo_pool` marker; `give_back` claims the marker with an atomic
  `dict.pop` and releases exactly once. No helper touches the budget.
- **The pre-flight probe answers a question once**: it converts a permanent
  connect failure into a millisecond error instead of a ~30s `PoolTimeout`, at
  the cost of a full extra connect. A DSN that has connected is recorded in
  `_reachable_keys`, so a pool *rebuild* (idle reaper, `PoolClosed` race) skips
  it — with the default `db_pool_reap_idle` (300s) below `db_conn_max_idle`
  (600s), a quiet database is reaped and rebuilt repeatedly and used to re-probe
  every time. The proof is revoked wherever its premise could have changed:
  `close_database` (Odoo's drop/rename path), stale-credential eviction, and any
  connect failure.
- **A cursor close only discards a DAMAGED connection**: `Cursor._close` asks
  `transaction_status` (`_connection_is_clean`) rather than treating any
  exception from `_do_rollback` as connection damage — that method also runs
  `transaction.clear()` and the rollback hooks, so an application bug there used
  to cost a warm pooled connection on top of the error.
- **One borrow, one deadline**: `db_borrow_timeout` is taken at the top of
  `ConnectionPool.borrow` and every step that can block derives its own timeout
  from it — the cold path's pre-flight probe (and its `_database_absent`
  fallback), the semaphore wait, `getconn`, and the direct maintenance connect.
  `_libpq_connect_timeout` clamps each libpq connect and returns `0` to mean
  *skip this connect*, never a value to pass on: libpq reads `connect_timeout=0`
  as "wait forever", so handing it a shrinking budget would make the tail of a
  deadline unbounded.
- **Maintenance databases are never pooled** (`postgres`, templates,
  `db_template`): `borrow` routes them to `_borrow_direct`, `give_back`
  closes them outright. A psycopg_pool cannot keep a database
  connection-free — it replaces every discarded connection to hold its count —
  and one idle connection to a template blocks
  `CREATE DATABASE … TEMPLATE`.
- **DDL needs client-side params**: PostgreSQL rejects `$N` in DDL structural
  positions, so `Cursor.execute` detects DDL (`ddl.py`) and inlines params as
  quoted literals. Schema-changing DDL additionally clears this connection's
  auto-prepared statements and this cursor's `TransactionSchemaCache`; *other*
  workers' prepared statements are healed via registry signaling → `drain_db`.
  Two different questions, two functions: `_ddl_keyword` reports the **leading**
  keyword (all param inlining needs — psycopg cannot bind server-side params
  into a multi-statement string at all), while `_changes_schema` scans **every**
  statement, because `BEGIN; ALTER …; COMMIT` would otherwise slip past
  invalidation and make the next `SELECT *` raise `FeatureNotSupported`.
- **Binary COPY reads the catalog under COPY's own lock**: binary COPY encodes
  values client-side from `pg_attribute` types, so a type read *before* the
  lock is not authoritative — a concurrent `ALTER` can commit while our `COPY`
  waits on that lock, and a same-width change (`int4`→`date`) is then written
  with no error. `_lock_table_for_bulk` takes `ROW EXCLUSIVE` (the mode `COPY`
  needs anyway) *before* the catalog read, and the facts it guards live on the
  cursor only until the transaction — hence the lock — ends. That is why
  `close_db`/`drain_*` carry no schema-cache invalidation: no process-global
  schema state exists to go stale.
- **Binary COPY types are OIDs, and `binary=True` is only a hint**: the catalog
  read returns `pg_attribute.atttypid`, not `pg_type.typname`, because
  `Copy.set_types()` resolves a *name* through psycopg's registry — which knows
  only built-in scalars, so an array column (`typname` `_int4`) raised
  `KeyError` even though psycopg dumps `int4[]` fine by OID. Domains resolve to
  their ultimate base type and enums to `text` (identical wire format); anything
  psycopg still has no binary dumper for — an extension type such as pgvector's
  `vector` or PostGIS's `geometry`, a composite, a range — is detected by
  `_can_dump_binary` *before* the COPY context opens and silently degrades to
  text COPY, which writes identical rows. A caller may therefore always pass
  `binary=True`; it never has to know the column types.
- **db→ORM dependency is one-directional**: the ORM injects
  `_OrmFlushingSavepoint` (as `BaseCursor._flushing_savepoint_cls`) and the
  `transaction` attribute at import; `cursor.py` guards that a
  transaction-bearing cursor never runs a non-restoring savepoint.
- **Password hygiene**: every DSN consumer routes through
  `dsn._expand_conninfo`; pool keys carry only a BLAKE2s fingerprint, and
  `Connection.dsn` strips the secret before logging.
- **`odoo.evented` guard**: `__init__._get_pool` uses
  `hasattr(odoo, "evented")` because `odoo.db` is importable without
  `odoo.init`'s monkeypatches (standalone scripts, tools) — not dead code.

## Tests

- **Tier 1 (no DB, ms)** — `odoo/db/tests/` via `cd addons/odoo && pytest`:
  pure modules (`ddl`, `dsn`, `errors`, `schema_cache` bookkeeping, `savepoint`
  depth accounting, `bulk`'s argument validation, `utils`' DSN/maintenance-db
  resolution) plus the two that only need stand-ins — `pool` (budget clamps and
  sharing, idle-pool reaping, permit accounting, reachability proof, close/drain
  matching, against a fake `psycopg_pool.ConnectionPool`) and `lifecycle`
  (what the session reset closes and spares, the health-check grace window,
  against a recording fake connection). Uses `sys.modules` stubs
  (`conftest.py`) so leaf modules import without executing
  `odoo/db/__init__.py`. What needs a real backend — lock-before-read and
  transaction scoping of the catalog facts, which types binary COPY can encode,
  borrow behaviour against an unreachable host — lives in the integration
  suite.
- **Integration (live DB)** —
  `odoo/addons/base/tests/test_db_cursor.py` (run with
  `--test-file … --stop-after-init` on a DB with `base` installed): cursor
  semantics, pool lifecycle/races, COPY, session reset, registry-drain wiring.

Put new tests in the lowest tier that can express them
(`doc/coding_guidelines.rst` §6).
