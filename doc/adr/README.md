# Architecture Decision Records

An **ADR** captures one significant architectural decision: its context, the
choice made, and the consequences. ADRs are immutable once accepted — to change
a decision, add a new ADR that supersedes the old one (and mark the old one
`Superseded by ADR-XXXX`).

These records document the framework-core architecture of the `19.0-marin`
fork. The companion overview is [`odoo/ARCHITECTURE.md`](../../odoo/ARCHITECTURE.md);
the boundaries several of these ADRs establish are enforced by
[`tooling/architecture/layer_check.py`](../../tooling/architecture/layer_check.py).

ADRs 0001–0004 are **retroactive**: they record decisions already embodied in
the code, written down so the reasoning is not lost. ADR-0005 is the decision to
enforce them.

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-layered-orm.md) | Layered ORM (Layer 0–3) | Accepted |
| [0002](0002-pure-python-orm-components.md) | Pure-Python ORM components with dependency injection | Accepted |
| [0003](0003-packagize-sql_db-into-db.md) | Decompose `sql_db.py` into a `db/` package | Accepted |
| [0004](0004-libs-vs-tools-split.md) | `libs/` (agnostic) vs `tools/` (Odoo-coupled) split | Accepted |
| [0005](0005-enforce-architecture-boundaries-in-ci.md) | Enforce architectural boundaries in CI | Accepted |
| [0006](0006-ratchet-countable-quality-gates.md) | Drift-zero ratchet for countable quality gates | Accepted |
| [0007](0007-db-backed-integration-test-gate.md) | DB-backed integration test gate | Accepted |
| [0008](0008-enforce-facade-boundary.md) | Enforce the public façade boundary (`odoo.addons` → `odoo.orm`) | Accepted |
| [0009](0009-close-the-enforcement-loop.md) | Close the enforcement loop (mainline gating, full façade scope, true floors) | Accepted |
| [0010](0010-consolidate-cache-compute-access-surfaces.md) | Consolidate the internal cache/compute access surfaces around `env._core` | Accepted |
| [0011](0011-persistence-backend-port.md) | Persistence backend port (`env.backend`) | Accepted |

## Template

```markdown
# ADR-XXXX: <short title>

- **Status:** Proposed | Accepted | Superseded by ADR-YYYY
- **Date:** YYYY-MM-DD

## Context
What forces are at play — technical, organisational, historical.

## Decision
The change we are making, stated in active voice.

## Consequences
What becomes easier, what becomes harder, and what we now must maintain.

## Enforcement
How the decision is kept true over time (tests, linters, CI gates), if any.
```
