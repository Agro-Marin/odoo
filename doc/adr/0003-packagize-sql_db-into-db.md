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
  documented and kept stable (see `doc/architecture/ARCHITECTURE.md`, "Seams").

## Enforcement

`tooling/architecture/layer_check.py`, contract `db-is-orm-agnostic`. For the
contract's live status, run the checker — this record does not restate it.

## Amendments

Append-only. An amendment corrects what this record says *about the repo*; it
never edits the decision above.

### 2026-08-07 — the live contract status is no longer restated here

The Enforcement section said the contract was "currently **clean at zero**". A
status is a fact about the tree at a moment, and this record is immutable, so
the sentence could only become false. Corrected in place: it is a citation, not
the decision.

### 2026-08-07 — the architecture front door moved to `doc/architecture/`

This record cited the front door at the path it held inside the core package
until 2026-08-07 (odoo/ARCHITECTURE.md — deliberately not backticked, because a
backticked path in this repo asserts that the file exists, and this one no
longer does). That page sat inside the core *package* while describing the
whole repository — the gate
catalog it indexes covers `addons/**` JS and the repo-wide `eslint`/`tsc`
ratchets — so it was filed one level below its own scope, and the two halves of
the architecture document cited each other across directories. Widening
`doc_link_gate.py` to the set found 15 broken references held together by
nothing. The set is now one flat directory, `doc/architecture/`, with the front
door at `doc/architecture/ARCHITECTURE.md`.

Corrected in place: the *Consequences* section's pointer to the seam documentation. It is a citation, not the decision.
