# ADR-0003: Decompose `sql_db.py` into a `db/` package

- **Status:** Accepted
- **Date:** 2026-06-23 (retroactive — records an existing decision)

## Context

Upstream Odoo's database access lives in a single `sql_db.py` that mixes
connection pooling, the cursor and its transaction semantics, savepoints, DDL
handling, bulk operations, and metrics. The module also reaches back into the
ORM (for cache flushing on savepoint rollback), coupling persistence to the
model layer.

## Decision

Decompose persistence into a focused `odoo/db/` package — `pool`, `cursor`,
`ddl`, `dsn`, `savepoint`, `schema_cache`, `bulk`, `metrics`, `lifecycle`,
`errors`, `utils` — and keep it **ORM-agnostic**: `db/` must not import
`odoo.orm`, `odoo.models`, `odoo.fields`, or `odoo.api`.

Where the ORM must participate in a database operation, it is **injected**
rather than imported. The flushing savepoint is the canonical example: the ORM
installs its implementation on `BaseCursor._flushing_savepoint_cls`, so the
cursor can flush the cache on rollback without `db/` knowing the ORM exists.

## Consequences

- Each persistence concern is a small, independently testable module (DDL
  detection, DSN normalisation, and savepoint logic are pure functions).
- The database layer can be reasoned about, and in principle reused, without
  the ORM.
- The cost: the ORM↔db seam is a set of injected hooks/attributes that must be
  documented and kept stable (see `odoo/ARCHITECTURE.md`, "Seams").

## Enforcement

`tooling/architecture/layer_check.py`, contract `db-is-orm-agnostic`
(currently **clean at zero**).
