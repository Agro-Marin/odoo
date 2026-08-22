# ADR-0030: Documentation that describes the tree is re-derived against it

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records decisions already enforced)

## Context

This fork's architecture documentation is load-bearing: `doc/adr/` carries the
arguments, `doc/architecture/` the present-tense description, and several core
packages their own module indexes. The split is deliberate — an ADR is past tense
and therefore true forever, a description is present tense and can only decay.

**Nothing held up the present-tense half.** `layer_check.py` enforces the
architecture's *contracts*, a different claim from its *map*. The doc-link gate
proves a referenced file exists and says nothing about whether a described
package still matches its directory. So the map was the one part that could rot
silently, and it did: it depicted four subdirectories that do not exist, and an
invented grouping node masked a real, undocumented module that does.

**Package indexes had the same problem one level down, with less protection.**
Several core packages document themselves with a per-module table. They are the
best documentation in the tree and were the least guarded: a module added to a
package appeared in no index until somebody remembered, while the README in
question *explicitly invited* additions — an instruction with no enforcement.

## Decision

**Prose that describes the tree is checked against the tree, in CI, in both
directions.**

### The subsystem map

**No fictional paths** — every path-shaped name exists. And a logical grouping
that is *not* a directory must say so, by writing itself in brackets; the checker
then reads it as a label and attributes what follows to the enclosing package.
That convention lets the map keep useful groupings without their being mistaken
for directories, which is the error that masked a real module.

### Package module indexes

Symmetric, and the symmetry is the point: **every module named by an index
exists**, and **every module in the package is named by its index**. A one-way
check lets the tree grow past its own documentation, which is the failure that
happened.

**Section scoping is load-bearing.** These READMEs contain other tables naming
modules, and some of those files are deliberately absent — one package's README
has a *Recently Removed* table whose every entry is correctly gone. A checker
scanning for backticked module names would report failures against a document
that is exactly right. Each index declares the heading that introduces it, and
only rows beneath it count.

**Opting a package in is explicit, and not opting it in is a recorded choice.**
The gate works from an inclusion list, so a package outside it cannot fail — a
new README carrying an inventory would be gated by nothing. A companion test
forces every core README to be classified as indexed or deliberately index-free.

## Alternatives considered

**Rely on the doc-link gate.** It proves a referenced file exists, a much weaker
claim than that a description still matches its subject. Every one of the map's
fictional subdirectories passed it, because none was a link.

**Generate the documentation from the tree instead of checking it.** Rejected,
and this shapes the rest: the value of these documents is the part a generator
cannot produce — what a package is *for*, which grouping is logical, why a
boundary exists. Generation replaces judgement with an inventory nobody needs,
since the tree already is the inventory. Gating the checkable half is what keeps
the unpublishable half honest.

**Rely on review.** The map contained four directories that do not exist,
through as many reviews as the surrounding work had. Nobody re-walks a tree
against a diagram by hand.

**Delete the map and let the tree speak for itself.** Rejected: a directory
listing does not say what a package is for, which groupings are meaningful, or
which module is the entry point.

## Consequences

- Adding a module to an indexed package means updating that index in the same
  change — real friction, and the price of the indexes being trustworthy.
- **The checkable half of these documents cannot rot silently. The rest still
  can.** Nothing verifies that a package's stated *purpose* is accurate or that
  a grouping is still right. This buys facts, not judgement.
- The bracket convention is part of the map's syntax, so a reader has to know it
  to write one.
- Only enumerated packages have their indexes gated, though the classification
  test makes the set a decision rather than an oversight.
- These gates read this repository only. `enterprise/` and `agromarin/` carry
  their own docs and are not covered.

## Enforcement

Two gates in `tooling/architecture/`, each declaring `ADR = "0030"`, both run by
`.github/workflows/architecture.yml`:

| gate | re-derives |
|---|---|
| `tooling/architecture/subsystem_map_check.py` | the subsystem map in `doc/architecture/module.md` against the package tree |
| `tooling/architecture/package_index_check.py` | each opted-in package README's module index against the package, both directions |

The wider discipline is enforced beside them: `tooling/doclinks/` proves
referenced files exist, and the architecture page's own suite re-derives the
figures it states. `tooling/architecture/test_gate_adr_coverage.py` checks that
both citations resolve to this record and that it is `Accepted`.
