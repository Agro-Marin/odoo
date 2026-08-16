# ADR-0030: Documentation that describes the tree is re-derived against it

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records decisions already enforced)

## Context

This fork's architecture documentation is unusually load-bearing: `doc/adr/`
carries the arguments, `doc/architecture/` carries the present-tense description,
and several core packages carry their own module indexes. The split is
deliberate and is stated in the register's own README — an ADR is past tense and
therefore true forever, a description is present tense and can only decay.

**Nothing held up the present-tense half.** `layer_check.py` enforces the
architecture's *contracts*, which is a different claim from its *map*. The
doc-link gate proves a referenced file exists and says nothing about whether a
described package still matches its directory. So the map was the one part of the
architecture documentation that could rot silently — and it did: it depicted four
subdirectories that do not exist, and an invented grouping node masked a real,
undocumented module that does.

**Package indexes had the same problem one level down, with less protection.**
Several core packages document themselves with a per-module table. They are the
best documentation in the tree and were the least guarded: a module added to a
package appeared in no index until somebody remembered, while the README in
question *explicitly invited* additions — an instruction with no enforcement
behind it.

## Decision

**Prose that describes the tree is checked against the tree, in CI, in both
directions.**

### The subsystem map

Two rules. **No fictional paths** — every path-shaped name in the map exists.
And a logical grouping that is *not* a directory must say so, by writing itself
in brackets; the checker then reads it as a label and attributes what follows to
the enclosing package. That convention is what lets the map keep useful
groupings without them being mistaken for directories, which is precisely the
error that masked a real module.

### Package module indexes

Symmetric, and the symmetry is the point: **every module named by an index
exists**, and **every module in the package is named by its index**. A one-way
check would let the tree grow past its own documentation, which is the failure
that actually happened.

**Section scoping is load-bearing, not an implementation detail.** These READMEs
contain other tables that also name modules, and some of those files are
deliberately absent — one package's README has a *Recently Removed* table whose
every entry is correctly gone. A checker that simply scanned for backticked
module names would report failures against a document that is exactly right. So
each index declares the heading that introduces it, and only rows beneath that
heading count as the inventory.

**Opting a package in is explicit, and not opting it in is a recorded choice.**
The gate works from an inclusion list, so a package outside it cannot fail — which
means a new README carrying an inventory would be gated by nothing and nobody
would notice. A companion test forces every core README to be classified as
either indexed or deliberately index-free, so the omission cannot be silent.

## Alternatives considered

**Rely on the doc-link gate.** It proves a referenced file exists, which is a
much weaker claim than that a description still matches its subject. Every one of
the map's fictional subdirectories passed it, because none of them was a link.

**Generate the documentation from the tree instead of checking it.** Rejected,
and this is the decision that shapes the rest: the value of these documents is
the part a generator cannot produce — what a package is *for*, which grouping is
logical, why a boundary exists. Generation would replace the judgement with an
inventory nobody needs, since the tree already is the inventory. Gating the
checkable half is what keeps the unpublishable half honest, because a document
whose facts are verified is one a reader can trust on the parts that are not.

**Rely on review.** The map contained four directories that do not exist,
through as many reviews as the surrounding work had. Nobody re-walks a tree
against a diagram by hand, and a reviewer who did would be doing the checker's
job worse.

**Delete the map and let the tree speak for itself.** Rejected: a directory
listing does not say what a package is for, which groupings are meaningful, or
which module is the entry point. The map exists precisely because the tree
under-determines those, and removing it would remove the answer rather than the
maintenance.

## Consequences

- Adding a module to an indexed package means updating that index in the same
  change. That is real friction on ordinary work, and it is the price of the
  indexes being trustworthy.
- **The checkable half of these documents cannot rot silently. The rest still
  can.** Nothing verifies that a package's stated *purpose* is still accurate, or
  that a grouping is still the right one. This record buys facts, not judgement,
  and reading a green gate as "the documentation is correct" would overclaim.
- The bracket convention is now part of the map's syntax, so a reader has to know
  it to write one — a small, real cost in exchange for keeping groupings.
- Only enumerated packages have their indexes gated, though the classification
  test means the set is a decision rather than an oversight.
- These gates read this repository only. `enterprise/` and `agromarin/` carry
  their own docs and are not covered here.

## Enforcement

Two gates in `tooling/architecture/`, each declaring `ADR = "0030"`, both run by
`.github/workflows/architecture.yml`:

| gate | re-derives |
|---|---|
| `tooling/architecture/subsystem_map_check.py` | the subsystem map in `doc/architecture/module.md` against the package tree |
| `tooling/architecture/package_index_check.py` | each opted-in package README's module index against the package, both directions |

The wider discipline they belong to is enforced beside them:
`tooling/doclinks/` proves referenced files exist, and the architecture page's
own suite re-derives the figures it states. `tooling/architecture/test_gate_adr_coverage.py`
checks that both citations resolve to this record and that it is `Accepted`.
