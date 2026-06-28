# ADR-0002: Pure-Python ORM components with dependency injection

- **Status:** Accepted
- **Date:** 2026-06-23 (retroactive — records an existing decision)

## Context

The hardest parts of the ORM to reason about and test are the field cache, the
computed-field engine, and the flush/recompute unit of work. In upstream Odoo
these are entangled with `Environment`, `Registry`, `BaseModel`, and the
database cursor, so they can only be exercised by spinning up a full registry
against a live database. That makes their invariants (cache coherency,
recompute convergence, field protection scopes) expensive to test and easy to
break.

## Decision

Implement the cache/compute/unit-of-work machinery as a self-contained package,
`odoo/orm/components/`, written as **pure Python with no `odoo` imports at
runtime**:

- `FieldCache` — value cache keyed by `(field, record id)`, dirty tracking.
- `ComputeEngine` — pending recomputations and field-protection scopes.
- `UnitOfWork` — the flush/recompute fixpoint loop.
- `ModelGraph` — the static field-dependency graph and recompute ordering.
- `OrmCore` — a thin façade unifying the above.

These objects receive their collaborators (the SQL executor, the recompute
callback, the registry's recompute order) by **injection**, rather than
importing the runtime.

## Consequences

- The cache and compute engines are unit-testable in isolation — see
  `odoo/orm/components/tests/` — without an `Environment` or a database.
- The contracts between the engine and the runtime are explicit (the injected
  callbacks), which makes the data-ownership boundary clear: the components own
  no model state.
- The cost: a little duplication of small helpers that the components cannot
  import from the framework, and the discipline of passing collaborators in.

## Enforcement

`tooling/architecture/layer_check.py`, contract
`orm-components-are-pure-python` (currently **clean at zero**). Test files under
`components/tests/` are exempt — tests may import freely.
