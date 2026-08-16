# Architecture Decision Records

An **ADR** captures one significant architectural decision: its context, the
choice made, and the consequences. ADRs are immutable once accepted — to change
a decision, add a new ADR that supersedes the old one (and mark the old one
`Superseded by ADR-XXXX`).

## Status is a claim about the tree, not a mood

| Status | Means | Gated? |
|---|---|---|
| `Proposed` | The decision is argued but **not built**. Naming code that does not exist yet is correct here. | exempt from the existence check |
| `Accepted` | The decision is **in the tree**. Every file, symbol and model the record names resolves. | `test_adr_coherence.py` enforces it |
| `Superseded by ADR-YYYY` | Replaced. Kept for the history. | as `Accepted`, until superseded |

`Accepted` is earned, not assigned at commit time. `TestReferencedNamesExist`
resolves every backticked path, `name()` and dotted model name in an `Accepted`
record against the tree, so the cheap way past the gate is to be honest about
status. This rule exists because ADR-0012 and ADR-0013 sat at `Accepted` for a
week describing a subsystem this repository has never contained — see their
Amendments.

## Three rules that keep a frozen record from rotting

**An ADR is past tense; `doc/architecture/ARCHITECTURE.md` is present tense.**
This is the rule the other two follow from. An ADR says *on this date, given
these forces, we chose X over Y* — a claim about a moment, and therefore true
forever.
`doc/architecture/ARCHITECTURE.md` says *this is how the system is today* — a
claim about now, which is why it is gated and re-derived. **A sentence in an ADR
written in the present tense about the tree is a bug**, because the record is
immutable and the tree is not: it can only become false, and nothing will
notice. Write "at
this decision the count was N", not "the count is N"; write "run the checker",
not "currently clean at zero". Gated by
`test_adr_coherence.TestNoLiveStatusClaims`.

**Never restate a number that lives somewhere else.** Ratchet floors, contract
counts and file counts belong to `tooling/ratchet/baselines/*.json` and
`layer_check.py`'s `CONTRACTS`. Cite the file, not the value. Every count
written into an ADR body so far has since gone stale, and one — ADR-0006's mypy
figure — never matched the baseline committed beside it. `typecheck.yml`'s
header states the same rule for the same reason: "two copies drift, and they
did." A *dated* measurement is not a restatement and is welcome: "measured 2074
on 2026-06-25" stays true, "the count is 2074" does not.

**Corrections go in an append-only `## Amendments` section.** Immutability
protects the *decision*, not a path that has since moved. An amendment is dated,
never edits the argument above it, and may correct a citation in place when it
says so. This is what ADR-0004's two silent post-acceptance rewrites should have
been.

These records document the framework-core architecture of the `19.0-marin`
fork. The companion overview is
[`doc/architecture/ARCHITECTURE.md`](../architecture/ARCHITECTURE.md); the
boundaries several of these ADRs establish are enforced by
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
| [0012](0012-attachment-storage-layers.md) | Attachment storage layers (object store, key policy, delivery) | Proposed |
| [0013](0013-content-placement.md) | Content placement — where an attachment's bytes are, as data | Proposed |
| [0014](0014-packagize-service-db.md) | Packagize service/db.py into `odoo/service/db/` | Accepted |
| [0015](0015-batch-reservation-in-action-assign.md) | Decide a batch's reservation before writing any of it | Accepted |
| [0016](0016-root-modules-are-foundational.md) | The root modules are foundational | Accepted |
| [0017](0017-t-out-on-a-recordset.md) | What `t-out` should render when the value is a recordset | Proposed |

## Template

```markdown
# ADR-XXXX: <short title>

- **Status:** Proposed | Accepted | Superseded by ADR-YYYY
- **Date:** YYYY-MM-DD

## Context
What forces are at play — technical, organisational, historical.

## Decision
The change we are making, stated in active voice.

## Alternatives considered
What else was on the table, and why each lost. **Required for every record from
the fourteenth on** (`ALTERNATIVES_REQUIRED_FROM` in
`tooling/architecture/test_adr_coherence.py`) — the earlier records predate the
rule and are not back-filled, because inventing a rejected alternative months
later is fiction. This is the section that makes a
record worth reading once the decision is old news: the Decision says what we
built, and anyone can read the tree for that; only this says what we already
tried not to build, which is the part a future reader would otherwise have to
re-derive by proposing it again. ADR-0010 is the worked example.

## Consequences
What becomes easier, what becomes harder, and what we now must maintain.

## Enforcement
How the decision is kept true over time (tests, linters, CI gates), if any.
A boundary added to `layer_check.py` sets `adr="XXXX"` on its contract, which
`test_layer_check.py` checks resolves to this file.

## Amendments
Omit until there is one. Append-only, newest last, each dated and headed with
what it corrects. Never edit the sections above except to fix a citation an
amendment announces.
```
