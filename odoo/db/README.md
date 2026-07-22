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
| `pool.py` | `ConnectionPool` (per-DSN psycopg_pool registry, borrow/give_back + semaphore budget, idle-pool reaper, stale-credential eviction, pre-flight probe, direct maintenance-DB path) and `Connection` | no |
| `bulk.py` | `_BulkAccessMixin`: `copy_from` (COPY, optional binary + pre-generated ids), `execute_values` | no |
| `savepoint.py` | `Savepoint` / `_FlushingSavepoint` (ORM state restore is injected by `odoo.orm.runtime.savepoint`) | yes* |
| `ddl.py` | DDL keyword detection + client-side param inlining (`$N` is rejected in DDL positions) | yes |
| `dsn.py` | DSN expansion/normalization (pool keys, password fingerprint), connect-error classification | yes |
| `errors.py` | `CURSOR_LOGGER_NAME`, retry taxonomy (`PG_RETRY_*`), `_log_sql_error` level demotion | yes |
| `lifecycle.py` | psycopg_pool `configure`/`reset`/`check` callbacks (adapters, prepare tuning, session reset, grace-windowed health check) | no |
| `schema_cache.py` | Process-global `(dbname, table)` caches for `copy_from` (id sequences, column types) | yes |
| `metrics.py` | `_MetricsMixin` (query counters, thread metrics, DEBUG per-table stats), `sql_counter` | yes* |
| `utils.py` | `connection_info_for`, `is_maintenance_db`, `categorize_query`, `seed_planner_stats`, adapter registration | no |

“Pure” = importable and testable without a database or the framework
(`yes*`: pure logic, but pulls `odoo.tools` on import).

## Load-bearing invariants (cross-module)

- **Semaphore accounting**: a `_pool_sem` permit is taken in
  `ConnectionPool.borrow`/`_borrow_direct` and travels with the connection via
  the `_odoo_pool` marker; `give_back` claims the marker with an atomic
  `dict.pop` and releases exactly once. No helper touches the semaphore.
- **Maintenance databases are never pooled** (`postgres`, templates,
  `db_template`): `borrow` routes them to `_borrow_direct`, `give_back`
  closes them outright. A psycopg_pool cannot keep a database
  connection-free — it replaces every discarded connection to hold its count —
  and one idle connection to a template blocks
  `CREATE DATABASE … TEMPLATE`.
- **DDL needs client-side params**: PostgreSQL rejects `$N` in DDL structural
  positions, so `Cursor.execute` detects DDL (`ddl.py`) and inlines params as
  quoted literals. Schema-changing DDL additionally clears this connection's
  auto-prepared statements and the process-global `schema_cache`; *other*
  workers are healed via registry signaling → `drain_db`.
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
  pure modules (`ddl`, `dsn`, `errors`, `schema_cache`, `savepoint` depth
  accounting). Uses `sys.modules` stubs (`conftest.py`) so leaf modules import
  without executing `odoo/db/__init__.py`.
- **Integration (live DB)** —
  `odoo/addons/base/tests/test_db_cursor.py` (run with
  `--test-file … --stop-after-init` on a DB with `base` installed): cursor
  semantics, pool lifecycle/races, COPY, session reset, registry-drain wiring.

Put new tests in the lowest tier that can express them
(`doc/coding_guidelines.rst` §6).
