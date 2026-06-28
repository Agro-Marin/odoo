# ADR-0011: Persistence backend port (env.backend)

- **Status:** Accepted
- **Date:** 2026-06-26

## Context

The DB-free ORM test tier (`odoo/orm/model_test_env.py`, ADR-0002 lineage) runs
real CRUD against an in-memory `DictBackend` instead of PostgreSQL. The way that
variant reached the model layer was a test-only concept — `transaction.storage`
— sniffed inline at **nine** sites across six hot-path CRUD mixins:

```python
storage = self.env.transaction.storage
if storage is not None:
    ...   # in-memory implementation, inline
# ... SQL implementation, inline ...
```

`create`, `write`, `read`, `search`, `unlink` each carried one or more such
branches, including an ~80-line in-memory domain evaluator (`_search_storage`).
This was a second persistence implementation smeared across the production model
mixins: the abstraction pointed the wrong way (production code naming a test
backend), the in-memory logic had no single home, and there was no real seam for
any future non-SQL backend.

## Decision

Introduce an explicit persistence-backend seam:

- `odoo/orm/runtime/backend.py::InMemoryBackend` collects the in-memory variant
  of every CRUD operation (`create_rows`, `update_rows`, `fetch`, `search`,
  `as_query`, `existing_ids`, `delete`) plus a `supports_parent_store`
  capability flag, in one place. Each method takes the operating `model`
  (recordset) and reuses the model's own ORM machinery; only the row I/O is
  redirected to the `DictBackend`.
- `Transaction` derives `backend = InMemoryBackend(storage) if storage else None`
  once, at construction. `Environment.backend` exposes it.
- The mixins dispatch through the seam:

  ```python
  if (backend := self.env.backend) is not None:
      return backend.search(self, domain, offset, limit, order)
  # ... SQL path ...
  ```

`env.backend is None` is the **PostgreSQL fast path**: production never
allocates a backend object, so the dispatch is a single attribute load with no
indirection (a deliberate null-object choice — SQL is the implicit default
backend, not a peer object). The SQL implementations stay inline in the mixins;
this ADR moves only the in-memory variant out and replaces the `storage`
sniffing with the `env.backend` abstraction.

## Consequences

- The in-memory backend has one testable home; production CRUD code no longer
  names `transaction.storage`/`DictBackend`, and the nine scattered
  `if storage is not None` branches collapse to one polymorphic check each.
- A genuine extension point exists for future backends (e.g. read-replica or
  alternative stores): implement the same operation surface, declare
  capabilities, hang it off the transaction.
- mypy dropped 1497 → 1494: the consolidated, fully-typed backend retired the
  `storage: typing.Any` parameter and the loosely-typed inline branches.
- Verified green across every gate: Tier-1 components, Tier-2 `model_test_env`
  (which exercises all nine in-memory paths), `layer_check` (no new crossings),
  ruff, and the DB-backed `base` suite (494 queries, 0 failed — identical to
  baseline) for the SQL paths.
- A residual single `if backend is not None` guard remains per operation — the
  irreducible cost of pluggability, kept branch-predictably free for the SQL
  case. Promoting the SQL path to an explicit `SqlBackend` (fully branch-free
  Strategy) is possible later but was judged not worth the SQL code motion now.

## Enforcement

`backend.py` lives in Layer 3 (`orm/runtime/`); it imports only `odoo.tools`
(the `Query` builder) at runtime and types against Layer 0–2 under
`TYPE_CHECKING`, so the existing layering contracts in
`tooling/architecture/layer_check.py` cover it (all eight clean at zero). The
model mixins reach the backend via the already-injected `env`, adding no
`orm/models → orm/runtime` import.
