# ADR-0011: Persistence backend port (env.backend)

- **Status:** Accepted
- **Date:** 2026-06-26

## Context

The DB-free ORM test tier (`odoo/orm/model_test_env.py`) runs real CRUD against
an in-memory `DictBackend`. That variant reached the model layer through a
test-only concept, `transaction.storage`, sniffed inline at **nine** sites
across six hot-path CRUD mixins:

```python
storage = self.env.transaction.storage
if storage is not None:
    ...   # in-memory implementation, inline
# ... SQL implementation, inline ...
```

`create`, `write`, `read`, `search` and `unlink` each carried one or more, plus
an ~80-line in-memory domain evaluator (`_search_storage`). A second
persistence implementation, smeared across production mixins, with the
abstraction pointing the wrong way — production code naming a test backend — no
single home for the in-memory logic, and no seam for any non-SQL backend.

## Decision

Introduce an explicit persistence-backend seam.

- `odoo/orm/runtime/backend.py::InMemoryBackend` collects the in-memory variant
  of every CRUD operation (`create_rows`, `update_rows`, `fetch`, `search`,
  `as_query`, `existing_ids`, `delete`) plus a `supports_parent_store`
  capability flag. Each method takes the operating `model` and reuses its ORM
  machinery; only row I/O is redirected to `DictBackend`.
- `Transaction` derives `backend = InMemoryBackend(storage) if storage else None`
  at construction; `Environment.backend` exposes it.
- The mixins dispatch through the seam:

  ```python
  if (backend := self.env.backend) is not None:
      return backend.search(self, domain, offset, limit, order)
  # ... SQL path ...
  ```

`env.backend is None` is the PostgreSQL fast path: production allocates no
backend object, so dispatch is one attribute load. A deliberate null-object
choice — SQL is the implicit default, not a peer. The SQL implementations stay
inline; this record moves only the in-memory variant out.

## Consequences

- The in-memory backend has one testable home; production CRUD no longer names
  `transaction.storage` or `DictBackend`.
- A real extension point exists for future backends: implement the operation
  surface, declare capabilities, hang it off the transaction.
- mypy dropped 1497 → 1494, retiring the `storage: typing.Any` parameter and
  the loosely typed inline branches.
- Verified green: Tier-1 components, Tier-2 `model_test_env` (which exercises
  all nine in-memory paths), `layer_check`, ruff, and the DB-backed `base` suite
  (494 queries, 0 failed, identical to baseline).
- One residual `if backend is not None` per operation remains — the irreducible
  cost of pluggability. Promoting the SQL path to an explicit `SqlBackend` was
  judged not worth the code motion then.

## Enforcement

`backend.py` is Layer 3 (`orm/runtime/`); at runtime it imports only
`odoo.tools` (the `Query` builder) and types against Layers 0–2 under
`TYPE_CHECKING`, so the existing layering contracts in
`tooling/architecture/layer_check.py` cover it — no new contract. Run the
checker for their live status. The mixins reach the backend via the already
injected `env`, adding no `orm/models → orm/runtime` import.

## Amendments

### 2026-08-07 — the live contract status is no longer restated here

Enforcement said the covering contracts were "all eight clean at zero". The
contract set has grown past eight, and a status is the checker's to report.

### 2026-08-07 — the port has outgrown this record's stated scope

The Decision scopes the port to the CRUD mixins. The dispatch surface has grown
to fifteen `env.backend` sites across nine files, **four of them in Layer 1**
(`odoo/orm/fields/`). A Layer-1 reach into a Layer-3 object travels through
`env` and creates no import, so `orm-layer1-below-models-and-runtime` is blind
to it by construction.

Recorded, not corrected: the widening is a real change to the port's blast
radius. The surface is pinned exact-mode in
`odoo/orm/tests/test_backend_dispatch_surface.py`, whose `DISPATCH_SITES` is the
authority on its size and on which sites are behaviourally lossy.

`fields/textual.py::_languages_in_sync_with` is **lossy**: the SQL branch reads
the stored jsonb translations and returns the languages whose term echoes the
written one, so an edit propagates; the in-memory branch has no jsonb column and
returns `{}`, so no translation ever follows a write. A DB-free test of
translation propagation would pass without exercising the behaviour.

### 2026-08-08 — the port had no PostgreSQL implementor, so `None` was one

This record says the port replaced nine inline `transaction.storage` sniffs.
Measured afterwards, it renamed them. `fields/reference.py` said so in its own
comment: "`env.backend is None` gates a prefetch SELECT, i.e. it reads as 'am I
on PostgreSQL?'."

All fifteen dispatch sites had the shape

    if (backend := self.env.backend) is not None:
        return backend.fetch(...)
    ...inline SQL...

so **`env.backend is None` was the PostgreSQL implementation** — an unnamed
branch across nine files. Consequences: `StorageBackend` described only the test
double and nothing checked the SQL path against its signatures; "am I on
PostgreSQL?" was spelled as a null check; a differential suite had one object to
run against.

`PostgresBackend` (`orm/runtime/backend.py`) is that branch, named.
`Transaction.backend` is non-optional, every null check is gone, and the
Protocol describes production as well as the double. It **adapts** the port to
the model's own `_*_sql` methods rather than moving the SQL: building it needs
`_field_to_sql`, `_table_sql`, the field objects and the `Query`, all model
knowledge. `InMemoryBackend` adapts the same port to `DictBackend`.

Two findings the extraction produced that reading had not:

- **The port's `delete` was missing an argument the operation needs.**
  `_unlink_process_batch` takes `Defaults` for the
  `many2one_company_dependents` cleanup; `delete(model, sub_ids, Data,
  Attachment)` had no place for it. Nobody noticed because the SQL path never
  went through the port. The signature now carries it; what remains is that the
  in-memory side does not use it.
- **Three sites are not two implementations of one operation.** The sharpest is
  `Many2many.read`: the SQL path fuses a JOIN into the *comodel's* `Query`,
  which already carries that model's domain, order and access filter, and gets
  one statement and the ordering free. `read_m2m_pairs(model, relation,
  column1, column2, ids)` has nowhere to put that query, so a backend without
  the fusion must read every pair and re-sort against an executed query. Two
  algorithms, not two implementations. It, `Reference._reference_exists` (a
  prefetch scan) and `Char._languages_in_sync_with` (needs the jsonb column) now
  branch on declared capabilities — `supports_joined_m2m_read`,
  `supports_column_scan`, `supports_translation_terms`.

This does not close the LOSSY notes. Four remain; the differential suite
(`odoo/addons/test_orm/tests/test_backend_differential.py`, 22 tests) is where
closing them would be proved. Naming the implementor is what lets that suite
compare two things instead of one thing and a fallthrough.

### 2026-08-09 — the differential suite's path was missing its `odoo/addons/` root

The previous amendment cited `test_orm/tests/test_backend_differential.py`;
`test_orm` is a bundled addon, so the path is
`odoo/addons/test_orm/tests/test_backend_differential.py`. The count stands at
22 `def test_` methods. Corrected in place.
