# ADR-0003: Decompose `sql_db.py` into a `db/` package

- **Status:** Accepted
- **Date:** 2026-06-23 (retroactive — records an existing decision)

## Context

Upstream keeps database access in one `sql_db.py` mixing connection pooling,
the cursor and its transaction semantics, savepoints, DDL, bulk operations and
metrics. It also reaches back into the ORM to flush the cache on savepoint
rollback, coupling persistence to the model layer.

## Decision

Decompose persistence into `odoo/db/` — `pool`, `cursor`, `ddl`, `dsn`,
`savepoint`, `schema_cache`, `bulk`, `metrics`, `lifecycle`, `errors`, `utils`
— and keep it **ORM-agnostic**: no import of `odoo.orm`, `odoo.models`,
`odoo.fields` or `odoo.api`.

Where the ORM must participate, it is **injected**. The flushing savepoint is
the canonical case: the ORM installs its implementation on
`BaseCursor._flushing_savepoint_cls`, so the cursor flushes the cache on
rollback without `db/` knowing the ORM exists.

## Consequences

- Each persistence concern is a small, independently testable module; DDL
  detection, DSN normalisation and savepoint logic are pure functions.
- The database layer can be reasoned about, and in principle reused, without
  the ORM.
- Cost: the ORM↔db seam is a set of injected hooks that must be documented and
  kept stable — `doc/architecture/ARCHITECTURE.md`, "Seams".

## Enforcement

`tooling/architecture/layer_check.py`, contract `db-is-orm-agnostic`. Run the
checker for the contract's live status.

## Amendments

### 2026-08-07 — the live contract status is no longer restated here

Enforcement said the contract was "currently **clean at zero**". That is a fact
about a moment in an immutable record, so it could only become false. Replaced
by a citation.

### 2026-08-07 — the architecture front door moved to `doc/architecture/`

This record cited the front door at the path it held inside the core package
until 2026-08-07. That page sat inside the core *package* while describing the
whole repository — the gate catalog it indexes covers `addons/**` JS and the
repo-wide `eslint`/`tsc` ratchets. Widening `doc_link_gate.py` to the set found
15 broken references. The set is now one flat directory, `doc/architecture/`,
with the front door at `doc/architecture/ARCHITECTURE.md`. Corrected in place:
the Consequences pointer to the seam documentation.
