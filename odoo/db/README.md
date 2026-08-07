# `odoo.db` — PostgreSQL connectivity layer

Fork-specific replacement for upstream's monolithic `sql_db.py`: psycopg 3
(server-side binding, pipeline mode) fronted by per-database
`psycopg_pool.ConnectionPool`s. Read this before editing; module docstrings
carry the detailed invariants — this file is the map.

## Module map

| Module | Contents | Pure? |
|---|---|---|
| `__init__.py` | Public API: `db_connect`, `close_db`/`close_all`, `drain_db`/`drain_all`, `pool_health`, lazy process-wide R/W + read-only `ConnectionPool` pair, `sql_counter` via module `__getattr__` | no |
| `cursor.py` | `BaseCursor` (hooks, flush convergence, savepoint seam) and `Cursor` (the `cr` object: execute/executemany/pipeline, DDL handling, close/commit/rollback guards) | no |
| `pool.py` | `ConnectionPool` (per-DSN psycopg_pool registry, borrow/give_back, idle-pool reaper, stale-credential eviction, pre-flight probe + reachability proof, direct maintenance-DB path, `health()`) and `Connection` | no |
| `budget.py` | `ConnectionBudget`: the shared `db_maxconn` cap, its permit semaphore and its saturation counter | yes |
| `stats.py` | `PoolStats`: borrow-wait histogram, pool churn and probe-outcome counters behind `ConnectionPool.health()` | yes |
| `reaper.py` | `IdlePoolReaper`: which quiet per-DSN pools to close and how often to look (the decision; the pool keeps the locking and teardown) | yes |
| `leaks.py` | `CheckoutTracker`: which connections are out, since when, from which thread and borrow site | yes |
| `breaker.py` | `CircuitBreaker`: failure gating with exponential backoff for an optional endpoint (the read replica) | yes |
| `lag.py` | `ReplicaLagGate` + `LAG_SQL`: sampled apply-lag ceiling that demotes stale reads to the primary | yes |
| `bulk.py` | `_BulkAccessMixin`: `copy_from` (COPY, optional binary + pre-generated ids), `execute_values` | no |
| `savepoint.py` | `Savepoint` / `_FlushingSavepoint` (ORM state restore is injected by `odoo.orm.runtime.savepoint`) | yes |
| `ddl.py` | DDL keyword detection + client-side param inlining (`$N` is rejected in DDL positions) | yes |
| `schema.py` | Schema DDL operations executed against a `cr`: create/alter tables, columns, constraints, foreign keys, indexes, views; `TableKind`, `SQL_ORDER_BY_TYPE` (relocated from the former `tools/sql.py`, ADR-0004) | no |
| `dsn.py` | DSN expansion/normalization (pool keys, password fingerprint), connect-error classification | yes |
| `errors.py` | `CURSOR_LOGGER_NAME`, retry taxonomy (`PG_RETRY_*`), user-fault taxonomy (`PG_USER_FAULT_*`), `_log_sql_error`'s three log tiers | yes |
| `lifecycle.py` | psycopg_pool `configure`/`reset`/`check` callbacks (adapters, prepare tuning, session reset, grace-windowed health check sized by `db_healthcheck_grace`) | no |
| `schema_cache.py` | `TransactionSchemaCache`: per-cursor, transaction-lifetime catalog facts for `copy_from` (id sequences, column types) | yes |
| `metrics.py` | `_MetricsMixin` (query counters, thread metrics, DEBUG per-table stats), `sql_counter` | yes* |
| `utils.py` | `connection_info_for`, `is_maintenance_db`, `categorize_query`, `seed_planner_stats`, adapter registration | no |

“Pure” = importable and testable without a database or the framework
(`yes*`: pure logic, but pulls `odoo.tools` on import).

> **This table is enforced.** `tooling/architecture/package_index_check.py`
> fails CI if a module in `odoo/db/` is missing from it, or if it names a module
> that no longer exists. Add the row in the same commit as the module.

## Load-bearing invariants (cross-module)

- **The budget bounds checked-out connections, not the server footprint.**
  Each per-DSN pool separately retains up to `maxconn` *idle* connections for
  `db_conn_max_idle`, so one process holds up to `maxconn × n_databases`
  backends — measured: four databases under `db_maxconn = 2` hold four
  backends, with never more than one checked out at a time. Size PostgreSQL's
  `max_connections` against that product, not against `db_maxconn`. Everything
  below is about how the *budget* is keyed and is orthogonal to this.

- **One budget per PostgreSQL server**: `db_maxconn` is the cap for a *server*,
  because that is what an operator sizes `max_connections` against, so
  `__init__.py` keys its `ConnectionBudget`s on the resolved `(host, port)` of
  `connection_info_for`. This has been wrong in both directions. A budget per
  *pool* let one worker hold `2 * db_maxconn` — 128 against a stock 100. One
  budget for *both* pools fixed that but bounded the sum of two independent
  servers once `db_replica_host` was set: the replica added no concurrency, and
  (verified against a live pair, `db_maxconn = 4`) four replica checkouts made
  the primary refuse. Endpoint-keying keeps both properties — same server, one
  budget; different servers, one each — and `db_maxconn_replica` sizes the
  replica's independently when it is genuinely distinct.

  The discriminator must be the *resolved endpoint*, never "is `db_replica_host`
  set": `test_enable` and `dev_mode=replica` deliberately point the read-only
  pool at the primary, and a replica host equal to the primary's is a legitimate
  way to exercise readonly routes. Treating those as two servers reinstates the
  `2 * db_maxconn` overshoot exactly. Both traps are pinned in
  `tests/test_budget_endpoints.py`, and the key's derivation in
  `tests/test_invariants.py`.

  The residual trade is unchanged where it still applies: within one server a
  single budget can starve itself (a request holding a R/W cursor while opening
  a read-only one), but `db_borrow_timeout` bounds that to a `PoolError`, and a
  saturated budget now names its holders (see the checkout tracker above).
- **Budget accounting**: a permit is taken in
  `ConnectionPool.borrow`/`_borrow_direct` and travels with the connection via
  the `_odoo_pool` marker; `give_back` claims the marker with an atomic
  `dict.pop` and releases exactly once. No helper touches the budget.
- **A saturated pool names its culprits**: every borrow records the connection
  in a `CheckoutTracker` with the holding thread and the borrow site, and every
  return removes it, so what is left is by definition still out. `db_maxconn`
  exhaustion therefore raises `PoolError: … budget (64) reached … oldest
  checkouts: 312.4s by odoo.service.http.request.5 at addons/x/models/y.py:42`
  instead of only the limit that was hit, and `db_leak_detection` warns about a
  checkout held past its threshold before the pool runs dry. The borrow site is
  captured unconditionally: the walk stops at the first application frame, so it
  costs 300 ns — less than the tracker's own 413 ns insert/delete pair — and
  gating it would have left the error mute exactly where it is needed. The leak
  warning has its own throttle, never the reaper's, or one would silence the
  other.
- **A replica is configured per keyword, and its failures decay**: all five of
  host/port/user/password/sslmode are overridable via `db_replica_*`, each
  falling back to the primary's `db_*` when unset, so a replica with its own
  role is expressible (only host/port used to be, and the inherited credentials
  failed with nothing to explain why). `Registry.cursor(readonly=True)` gates
  the replica behind a `CircuitBreaker`: the flat 20-minute demotion it replaces
  cost that long for a transient blip and never re-checked, where the breaker
  opens for a second and doubles to the same 20-minute ceiling, so the worst
  case is unchanged and a blip recovers immediately. Measured against a real
  streaming replica: stopped mid-traffic and restarted, read-only cursors
  resumed **5.1 s** after the outage. One caller probes at a time, or a dead
  replica draws a connection attempt from every request that arrives while it
  is out.
- **Staleness is bounded, not merely tolerated**: read-only routes are chosen
  because they tolerate stale reads, but "tolerates any amount, unmeasured" is
  not a guarantee. `db_replica_max_lag` (0 = off) demotes reads to the primary
  while the replica's *apply* lag exceeds it, sampled at most every
  `max(1, value/4)` seconds on a cursor already borrowed for the request — so an
  enabled ceiling costs one query per sample, not per request, and a disabled
  one costs nothing. The measurement is the subtle part:
  `pg_last_xact_replay_timestamp()` grows without bound on an *idle* primary
  (measured 43 s against a standby with nothing left to apply), so `LAG_SQL`
  reports zero whenever the standby has replayed everything it received and
  falls back to the replay timestamp only when WAL is genuinely outstanding. It
  therefore bounds apply lag and not receive lag: WAL the standby has not
  received is indistinguishable from an idle primary without querying
  `pg_stat_replication` on the primary, which would defeat the point of reading
  elsewhere. A measurement that fails is recorded as healthy — a replica that
  cannot answer is one whose failure the breaker sees anyway, and demoting on
  a failed *question* would demote on no evidence.
- **The trades this layer makes are countable**: a shared budget that can
  starve itself, and a probe that trades a connect for a fast permanent
  failure, are only defensible if an operator can watch them. `PoolStats`
  records the borrow-wait histogram, pool churn and probe outcomes; the budget
  counts its own exhaustions (it is shared, so the count belongs to it, not to
  whichever pool asked last); `ConnectionPool.health()` and `db.pool_health()`
  render both alongside the live per-DSN psycopg_pool view. Cost on the borrow
  path is 230 ns, against a ~140 µs cursor cycle.
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
- **The schema cache holds two different lifetimes**: the memoized catalog
  reads expire whenever DDL lands (`clear_catalog_facts`, called from
  `discard_cached_plans`), but `locked_tables` — the ledger of which tables
  this transaction has already locked — expires only where the locks themselves
  do. DDL does not end a transaction, so the `ROW EXCLUSIVE` lock survives it
  and re-issuing `LOCK TABLE` is a wasted round-trip; a `ROLLBACK TO SAVEPOINT`
  *does* release locks taken inside the savepoint (verified against PG 18),
  which is why `_on_rollback_to_savepoint` still calls the full `clear()`.
- **One resolution of the caller's table name**: `bulk._table_identifier`
  splits on `.` and builds a `psycopg.sql.Identifier`, and every consumer uses
  it — `LOCK TABLE`, `COPY`, and (via `Identifier.as_string()`) the
  `%s::regclass` catalog reads and `pg_get_serial_sequence`. They used to
  disagree: the lock and the COPY quoted the name as one identifier while the
  catalog lookups passed the raw string to casts that parse and case-fold, so
  `MyTable` locked `"MyTable"` but read its column types from `mytable` (an
  `int4` column read as `oid` stored `4000000000` as `-294967296`, silently),
  and `s1.t` became the single identifier `"s1.t"`, which matches no
  schema-qualified table.
- **`binary=True` means "the faster encoding", not "binary"**: `copy_from`
  degrades to text on two independent grounds, both decided in
  `_binary_pays_off` where the column OIDs already are. psycopg has no binary
  dumper for extension/composite/range types (`_can_dump_binary`); and it has
  no float→numeric binary dumper, so each numeric cell costs a `Decimal`
  conversion. Measured, 20k rows × 20 columns: binary beats text at 0–5 numeric
  columns (−60% to −9%) and loses from 6 (+15%, +291% at 20), so
  `_BINARY_NUMERIC_MAX_FRACTION` puts the crossover at a quarter of the row.
  The ORM used to duplicate this as "any numeric column at all", which forfeited
  9–56% on the ordinary Odoo row shape (a few Monetary/Float fields among many
  char/int/date/m2o columns). Both fallbacks insert identical rows, so a caller
  never has to know its column types.
- **The statement entry points are marked, and the marks are enforced**: every
  method that puts a statement on the wire (`execute`, `executemany`,
  `execute_values`, `copy_from`, `copy`) calls `_before_statement()`, a no-op
  in this layer whose purpose is to *name* that set. `odoo.tests.cursor.
  TestCursor` takes its rollback savepoint before the first statement of a
  test; only its `execute()` override did so, and the bulk APIs it does not
  override reach the real cursor via `__getattr__`, so their writes landed
  outside the savepoint and survived the rollback. `TestCursor` now forwards
  each marked name explicitly and two tests pin the lists against each other,
  so a write API added without a forwarder fails rather than escaping. It
  cannot be done by hooking the wrapped cursor instead: several `TestCursor`s
  share one real cursor, so such a hook opens whichever is innermost rather
  than the one the caller holds. Argument validation runs before the mark — a
  rejected call issues no statement and must not open a savepoint.
- **`BaseCursor` declares only what it has**: it used to inherit
  `psycopg.Cursor` under `TYPE_CHECKING` and `object` at runtime, so mypy
  believed every cursor flavour — including `TestCursor`, which forwards by
  `__getattr__` — had psycopg's whole API. `cr.stream(...)` type-checked clean;
  that is how the bulk-write bypass above stayed invisible to the type checker.
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
- **Odoo's session GUCs set defaults, they do not override the operator**:
  `_session_gucs` renders `db_session_gucs` (`jit=off,work_mem=16MB`) into `-c`
  switches, skipping any GUC already named in the operator's `options` kwarg,
  URI `?options=`, or `PGOPTIONS`. libpq lets the last `-c` win, so appending
  unconditionally silently overrode them — `PGOPTIONS='-c work_mem=64MB -c
  jit=on'` arrived as `work_mem=16MB`/`jit=off`, with nothing in any log.
  `idle_session_timeout` is still applied unconditionally: it is derived from
  `db_conn_max_idle` and is what keeps the server from reaping a connection the
  pool still considers warm.
- **Password hygiene**: every DSN consumer routes through
  `dsn._expand_conninfo`; pool keys carry only a BLAKE2s fingerprint, and
  `Connection.dsn` strips the secret before logging.
- **`odoo.evented` guard**: `__init__._get_pool` uses
  `hasattr(odoo, "evented")` because `odoo.db` is importable without
  `odoo.init`'s monkeypatches (standalone scripts, tools) — not dead code.

## Tests

- **Invariants are enforced, not just described** — `odoo/db/tests/test_invariants.py`
  turns the rules on this page into structural checks: only the two borrow paths
  touch the budget, `borrow` diverts maintenance databases, both borrow paths
  track their checkout and `give_back` releases it before any early exit, the
  leak warning uses its own throttle rather than the reaper's, a password never
  reaches a pool key, `conninfo_to_dict` has one caller, `_libpq_connect_timeout`
  never returns a value libpq would read as "wait forever", the budget is keyed
  on the resolved endpoint rather than the presence of `db_replica_host`, the
  two schema-cache clears keep their distinct call sites, and `_changes_schema`
  cannot miss a hidden statement. Each was verified to fail when its invariant is violated.
  Add the check here when you add an invariant above.

- **Tier 1 (no DB, ms)** — `odoo/db/tests/` via `cd addons/odoo && pytest`:
  pure modules (`ddl`, `dsn`, `errors`, `schema_cache` bookkeeping, `savepoint`
  depth accounting, `bulk`'s argument validation and encoding cost model,
  `utils`' DSN/maintenance-db resolution, `budget`/`stats` accounting, `reaper`
  policy and throttle, `leaks` checkout bookkeeping, `breaker` backoff schedule,
  `lag` ceiling and its sampling, one budget per resolved endpoint in
  `budget_endpoints`)
  plus the two that only need stand-ins — `pool` (budget clamps and sharing,
  idle-pool reaping, permit accounting, reachability proof, close/drain
  matching, against a fake `psycopg_pool.ConnectionPool`) and `lifecycle`
  (what the session reset closes and spares, the health-check grace window,
  against a recording fake connection). Uses `sys.modules` stubs
  (`conftest.py`) so leaf modules import without executing
  `odoo/db/__init__.py`. What needs a real backend — lock-before-read and
  transaction scoping of the catalog facts, which types binary COPY can encode,
  borrow behaviour against an unreachable host — lives in the integration
  suite.
- **Tier 2 (real `import odoo`, no DB)** —
  `odoo/orm/tests/test_replica_breaker.py`: how `Registry.cursor(readonly=True)`
  gates a failing or lagging replica, since the breaker and the lag gate live
  here but their only caller is the ORM registry.
- **Integration (live DB)** —
  `odoo/addons/base/tests/test_db_cursor.py` (run with
  `--test-file … --stop-after-init` on a DB with `base` installed): cursor
  semantics, pool lifecycle/races, COPY, session reset, registry-drain wiring.

Put new tests in the lowest tier that can express them
(`doc/coding_guidelines.rst` §6).
