# ADR-0029: Inventory the dependencies that produce no import edge

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records decisions already enforced)

## Context

The fork's two foundational boundary decisions both reason about **import
edges**: the layer contracts (ADR-0001, ADR-0005) and the façade boundary
(ADR-0008). That is the right model for most boundaries, and it is blind to the
ones that carry the most weight in this framework — because the ORM's widest
dependencies are not taken by importing anything.

Five channels, each carrying a real dependency, each invisible to every import
gate.

**The `env` seam.** The contracts forbidding Layer 1 and Layer 2 from importing
the runtime are clean, and they always will be — *because that is not how those
layers reach the runtime*. They reach it through `self.env`, on every call, and
an `env.registry` produces no import edge at all. The ORM's widest cross-layer
dependency was invisible to the checker guarding everything around it.

**The `pool` seam.** The same argument with a channel the first one missed:
`self.pool` **is** the registry (`odoo/orm/models/metaclass.py` types it as one,
imported from the runtime package), so every `model.pool.<member>` is a
Layer-N-to-Layer-3 access that produces no edge and moves no gate.

**String-keyed model reach.** `core-does-not-depend-on-addons` reasons about
imports, so it is blind to the framework's largest real coupling to its own
consumer: core packages reach roughly thirty models living in `odoo/addons/base`
through subscripts like `env["res.users"]`, which compile to no import
whatsoever. The import contract reported its two tolerated edges while that
entire surface passed unmeasured.

**Which members are called on those models.** A model name is not a contract;
the members called on it are. The model inventory is green for any change that
adds no *model* — so calling a newly-invented hook on `res.users` from the ORM
passes it, while being exactly the kind of coupling the inventory exists to
track.

**Worker-thread bookkeeping.** Per-request identity — database name, user id,
url, SQL counters, cursor mode — is stashed as attributes on the thread object
and read back by the logger, the profilers and the WSGI handler. Written as a
bare attribute read off the current thread object, that dependency is untyped and
unseeable: no import, no declaration, and no way for a checker to know what the
attribute set even is.

ADR-0024 records the same class of blind spot for mixin composition, arriving
through `self` rather than through a seam. This record is its companion: same
diagnosis, four more channels.

## Decision

**Every channel that carries a dependency without producing an import edge is
inventoried, and the inventory is held.**

| channel | how it is held |
|---|---|
| the `env` seam | a drift-zero member set — widening it is an edit, not an accident |
| the `pool` seam | the same, for the channel the first gate missed |
| models reached by string key | an exact-mode set: a new model dependency from core fails CI |
| members called on those models | ratcheted `(model, member)` pairs |
| worker-thread attributes | declared **once** as a Protocol and handed out through an accessor, so readers are typed and the attribute set is visible to a checker |

The worker-thread case is the one where the fix is structural rather than
merely observational: `odoo/libs/worker_thread.py` declares the contract as a
Protocol and `current_worker_thread` hands it out, which replaces an untyped
idiom with a typed one. The others record a surface the framework genuinely has;
this one narrows the surface as it records it.

**Measurement precedes judgement, deliberately.** None of these gates asserts
that the reach is wrong. Three of the five exist to make a surface countable so
that a later decision can be taken on evidence — the model inventory's own
docstring names that next step, promoting the interfaces into core as protocols
with their implementations in `odoo/addons/base`, and the member inventory is both the
measurement that step needs and what would keep a promoted interface honest
afterwards.

## Alternatives considered

**Extend the import checker to model these channels.** Rejected because the
information is not in the import graph to extend. An attribute access through
`self.env`, a string subscript, and an attribute on a thread object are three
different analyses, none of them an import edge, and folding them in would not
extend that checker but replace it — while making its own contract model answer
questions it was not built for.

**Forbid the reaches instead of counting them.** The end state for at least the
model channel, and not available first: deciding which interfaces belong in core
requires knowing which models and which members are actually reached, which is
precisely what these inventories produce. The same relationship ADR-0020 has to a
declared client API.

**Rely on the typechecker.** It cannot help with the largest channel: a
string-keyed subscript yields a recordset whatever the key is, so the model
identity that constitutes the dependency is not in the type. Typing is what
*fixed* the worker-thread channel, and it is the right tool where the contract
can be named — which is why that one is a Protocol and the others are
inventories.

**Rely on review.** Rejected on the fork's standing argument, made in ADR-0016
for the root modules and in ADR-0006 generally: a property that is true and
unenforced is a property that stays true until someone has a reason. Every one of
these five surfaces was true, unenforced, and unmeasured before its gate existed,
and none of them was believed to be a problem at the time.

## Consequences

- The framework's coupling to its own consumer is a number rather than an
  impression, and a new one is a commit that has to update an inventory.
- **Five more inventories to maintain**, each of which must be updated in the
  same change that widens what it covers. That is the intended friction and it is
  a real cost on ordinary work.
- The two seams being drift-zero means widening the `env` or `pool` surface is a
  decision somebody makes on purpose, rather than a member that appears.
- Counting is not disapproval. A rising member count may be correct, and reading
  these gates as pressure to reduce would misread them — the pressure they apply
  is to be deliberate.
- Coverage is this repository's framework packages. The sibling repos reach the
  same models through the same channels and are not measured here, which is the
  same scope limit ADR-0009 records for the façade.
- The worker-thread Protocol only helps code that goes through it. A new bare
  attribute read is caught by the gate, not prevented by the type system.

## Enforcement

Five gates in `tooling/architecture/`, each declaring `ADR = "0029"`, all run by
`.github/workflows/architecture.yml`:

| gate | inventories |
|---|---|
| `tooling/architecture/env_surface_check.py` | the members reached through the `env` seam |
| `tooling/architecture/pool_surface_check.py` | the members reached through the `pool` seam |
| `tooling/architecture/env_model_surface_check.py` | the addon-owned models the framework reaches by string key |
| `tooling/architecture/model_member_surface_check.py` | the members it calls on them |
| `tooling/architecture/worker_thread_surface_check.py` | the framework's reach into worker-thread bookkeeping |

`tooling/architecture/test_gate_adr_coverage.py` checks that each citation
resolves to this record and that it is `Accepted`. For any inventory's live
contents, run its gate — this record does not restate them.
