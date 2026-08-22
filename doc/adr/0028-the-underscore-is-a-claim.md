# ADR-0028: In client code the underscore is a claim, and it is budgeted

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records a decision already enforced)

## Context

A leading underscore is the only thing marking a member as internal in this
tree's JavaScript, and nothing checked it. `doc/coding_guidelines.rst` defines
the convention for **Python** only — where it also governs RPC exposure — so in
the client `_` meant whatever each file decided.

Measured, it meant very little, and the reason is a pattern that looks like an
improvement.

Splitting a long class into satellite modules is good work: the satellites are
separately unit-tested with mock objects, and mutation-testing them confirms the
tests discriminate. What such a split does *not* do is narrow the interface. One
222-line satellite touches 21 members across three classes it does not own,
twelve of them private, and **writes** six.

So coupling that used to be `this._x` inside one long class became `record._x`
across twenty files — where no gate sees it, and **the naming convention
actively says it is not there.** The split moved coupling out of a place where it
was at least visibly internal into a place where it reads as an external API.

The same shape ADR-0024 records for mixins, by a different route: a
decomposition that improves testability while leaving the dependency structure
untouched, invisible to a checker family that needs an import edge.

## Decision

**Cross-module access to another module's private members is counted, and the
count is a ratchet.**

Figures live in the gate's regenerated `MEASURED` block, and a stale docstring
fails CI — a discipline this gate needed in its own right: its opening paragraph
once asserted a count of accesses and files the tree had already moved away
from, with three further numbers stale alongside it.

Three distinctions carry the design.

**Reads and writes are counted separately.** A read of a foreign private is a
coupling; a write is a coupling *and* a mutation of state whose owner does not
know it changed. Not the same debt, not reported as one.

**Members no module declares are reported apart and not counted.** A private
created by assignment rather than declaration cannot be attributed to an owner,
and a case the tool cannot decide is not evidence of a defect — the treatment
ADR-0021's shape gate gives services whose return value it cannot follow.

**The public-member count is reported alongside.** Every private-access metric
falls to zero by deleting the underscores, which changes no coupling. Reporting
both puts that trade in the same diff.

## Alternatives considered

**Forbid cross-module private access outright.** Rejected as a starting point:
the tree has hundreds of such accesses, they arrived through refactors that were
otherwise improvements, and a drift-zero rule would need an exception list long
enough to mean nothing. A ratchet states the debt and makes it fall.

**Make the convention a lint rule instead.** Rejected for ADR-0025's and
ADR-0019's reason: a finding folded into the repo-wide aggregate is one unit in
five figures, and a new violation would be invisible.

**Extend the Python convention to the client and leave it at that.** The guide's
rule is what the client lacks, and writing it down changes nothing on its own —
which is the finding. `_` was already the convention by custom; it was
unmeasured, and therefore untrue.

**Count only writes.** Attractive, because writes are the sharper defect.
Rejected because reads are what make a private part of an interface: once twenty
files read `record._saveInFlight`, renaming it is a cross-module change whether
or not anyone wrote to it.

## Consequences

- The convention means something measurable. A refactor that moves coupling from
  inside a class to across module boundaries shows up as a rising number rather
  than a clean diff.
- **A satellite split is no longer automatically a win.** It has to narrow the
  interface, not merely relocate it, and the budget distinguishes the two.
- The number can be gamed by removing underscores; the guard is social, with the
  public-member count printed beside it. No gate can tell a deliberate promotion
  to public API from a cosmetic one.
- Coverage is the client's core addon. The same property in other addons is
  unmeasured.
- The gate says nothing about whether a *public* member should have been
  private. It measures respect for the claim, not the correctness of the claim.

## Enforcement

One gate in `tooling/architecture/`, declaring `ADR = "0028"`, run by
`.github/workflows/architecture.yml` against a baseline in
`tooling/ratchet/baselines/`:

| gate | ratchets |
|---|---|
| `tooling/architecture/js_private_access.py` | cross-module private reads and writes, against its regenerated `MEASURED` block |

`tooling/architecture/test_gate_adr_coverage.py` checks that the citation
resolves to this record and that it is `Accepted`. Run the gate for live
figures.
