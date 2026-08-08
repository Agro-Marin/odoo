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
`tooling/architecture/layer_check.py` cover it — no new contract was needed. For
their live status, run the checker; this record does not restate it. The model
mixins reach the backend via the already-injected `env`, adding no
`orm/models → orm/runtime` import.

## Amendments

Append-only. An amendment corrects what this record says *about the repo*; it
never edits the decision above.

### 2026-08-07 — the live contract status is no longer restated here

The Enforcement section said the layering contracts covering `backend.py` were
"all eight clean at zero". Both halves were claims about a moment written into
an immutable record: the contract set has grown past eight, and a status is the
checker's to report. Corrected in place — it is a citation, not the decision.

### 2026-08-07 — the port has outgrown this record's stated scope

The Decision scopes the port to "the model mixins
(`create`/`write`/`read`/`search`/`unlink`)". The dispatch surface has since
grown to fifteen `env.backend` sites across nine files, **four of them in
Layer 1** (`odoo/orm/fields/`), which this record does not contemplate. A Layer-1
reach into a Layer-3 object travels through `env` and creates no import, so
`orm-layer1-below-models-and-runtime` is blind to it by construction.

Recorded rather than corrected in place: the decision is right about what was
decided, and the widening is a real change to the port's blast radius that a
future reader should meet as a fact, not as a silent edit to a 2026 record. The
surface is pinned exact-mode in
`odoo/orm/tests/test_backend_dispatch_surface.py`, whose `DISPATCH_SITES` is the
authority on its size and on which sites are behaviourally lossy — this record
does not restate either.

The most recent addition, `fields/textual.py::_languages_in_sync_with`, is
**lossy**: the SQL branch reads the stored jsonb translations and returns the
languages whose term merely echoes the written one, so an edit propagates to
them; the in-memory branch has no jsonb column to compare and returns `{}`, so on
that backend no translation ever follows a write. That is the shape of divergence
the pin exists to make visible — a DB-free test of translation propagation would
pass without exercising the behaviour at all.
