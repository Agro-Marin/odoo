# ADR-0034: The core's import graph is acyclic, which direction alone does not give

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records a decision already enforced)

## Context

ADR-0001 organises the ORM as layers with a single downward dependency
direction, and ADR-0005 enforces that direction in CI. Both are about **where an
edge may point**. Neither says anything about a cycle, and a cycle is invisible
to them by construction: **every edge of a cycle can sit inside one layer and
break no contract.** The boundary checker would report a tangle of mutually
importing modules as perfectly clean, provided none of the edges crosses a
declared boundary.

That asymmetry had already been identified and closed on the other side of the
tree. ADR-0019 records the same hole for the client and the gate that fills it,
with a concrete failure: a cycle whose outcome depended entirely on which module
the bundle evaluated first — correct through three entry points and broken
through three others. The Python core had exactly the same hole and no gate.

A cycle is also the failure that hides best. It produces no import error, the
typechecker is content, and whether it hurts depends on evaluation order — so it
can sit in a tree for a long time being harmless, and become a defect the day an
import is added somewhere unrelated.

## Decision

**The framework core's import graph is acyclic, drift-zero.**

This is a separate gate from the boundary checker rather than a rule added to it,
for the reason the two questions differ: one asks whether an edge is *permitted*,
the other whether the set of edges contains a loop. A checker that answered both
would have to hold the whole graph to answer the second, which is not what the
contract model is for.

It mirrors the client gate that ADR-0019 records, deliberately and by the same
argument. Where the fork has the same property in both languages, it is held by
the same shape of gate — the pattern ADR-0024 follows for mixin composition and
ADR-0025 for function length.

## Alternatives considered

**Add cycle detection to the boundary checker.** Rejected on separation of
question, and on the practical point that the contract table is what makes that
checker readable: a contract says who may import whom, and acyclicity is a
property of no particular pair. Folding it in would make the gate's own output
harder to act on for both kinds of finding.

**Rely on the layer contracts.** They cannot see it, and this is not a matter of
tuning: a cycle entirely within one layer violates no direction rule. The
contracts were green over the client's six-module cycle for exactly this reason,
and the Python side had no reason to be different.

**Rely on the tests.** A cycle is order-dependent, so the suite exercises
whichever order the imports happen to produce. The client incident is the proof:
the same cycle was correct or broken depending on entry point, so a green suite
was evidence about one path and nothing more.

**Tolerate cycles and ratchet the count down.** The usual move for a backlog, and
unnecessary here — the property already held when the gate landed, so it could be
drift-zero from the first commit rather than starting from a floor. Pinning an
invariant that already holds is the cheapest it will ever be, which is the same
argument ADR-0020 makes for the face boundary.

## Consequences

- A cycle in the core fails immediately rather than becoming an
  order-of-evaluation hazard nobody can attribute later.
- **A deferred import can no longer be used to quietly close a loop.** Breaking a
  cycle with a function-local import satisfies the letter of an import graph
  while leaving the dependency; ADR-0001 records the inversion seam that replaced
  exactly that pattern, and this gate is what keeps the replacement from being
  undone.
- The cost is that a genuinely mutual dependency must now be resolved
  structurally — by inversion, by moving the shared piece down a layer, or by
  merging the modules — rather than deferred.
- Scope is the framework core. The bundled addons are not covered, and this
  record does not claim they are.
- Both trees now hold acyclicity, but under two records: this one and ADR-0019
  for the client. That split follows the gates rather than the concept, and is
  noted so a reader looking for "the cycle decision" finds both.

## Enforcement

One gate in `tooling/architecture/`, declaring `ADR = "0034"`, run by
`.github/workflows/architecture.yml`:

| gate | holds |
|---|---|
| `tooling/architecture/py_cycle_check.py` | the framework core's import graph contains no cycle |

`tooling/architecture/test_gate_adr_coverage.py` checks that the citation
resolves to this record and that it is `Accepted`. For the gate's live status,
run it — this record does not restate one.
