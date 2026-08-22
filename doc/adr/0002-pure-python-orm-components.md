# ADR-0002: Pure-Python ORM components with dependency injection

- **Status:** Accepted
- **Date:** 2026-06-23 (retroactive — records an existing decision)

## Context

The field cache, the computed-field engine and the flush/recompute unit of work
are the hardest parts of the ORM to reason about. Upstream entangles them with
`Environment`, `Registry`, `BaseModel` and the cursor, so exercising them needs
a full registry against a live database. That makes cache coherency, recompute
convergence and field-protection scopes expensive to test and easy to break.

## Decision

Implement that machinery as `odoo/orm/components/`, **pure Python with no
`odoo` imports at runtime**:

- `FieldCache` — value cache keyed by `(field, record id)`, dirty tracking.
- `ComputeEngine` — pending recomputations, field-protection scopes.
- `UnitOfWork` — the flush/recompute fixpoint loop.
- `ModelGraph` — static field-dependency graph, recompute ordering.
- `OrmCore` — façade over the above.

Collaborators (SQL executor, recompute callback, registry recompute order) are
**injected**, not imported.

## Consequences

- The cache and compute engines are unit-testable without an `Environment` or a
  database — `odoo/orm/components/tests/`.
- The engine↔runtime contracts are explicit, and the components own no model
  state.
- Cost: small helpers duplicated rather than imported, and the discipline of
  passing collaborators in.

## Enforcement

`tooling/architecture/layer_check.py`, contract
`orm-components-are-pure-python`. Tests under `components/tests/` are exempt.
Run the checker for the contract's live status.

## Amendments

### 2026-08-07 — the live contract status is no longer restated here

Enforcement said the contract was "currently **clean at zero**". That is a fact
about a moment in an immutable record, so it could only become false. Replaced
by a citation.
