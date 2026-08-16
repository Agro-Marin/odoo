# ADR-0018: Upstream is a baseline — there is no merge, and none is wanted

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records a decision already in force)

## Context

This repository was cut from upstream Odoo's `19.0` branch and both lines have
moved since. Measured 2026-08-14: the merge base is `4ad397e94b4`, dated
2026-01-22; `19.0-marin` carries 2,860 commits since it, and upstream's `19.0`
carries 4,191.

The fork's principal work has been structural. Upstream concentrates the core in
a few very large modules; this fork decomposed them — the ORM into layers
(ADR-0001), `sql_db.py` into a package (ADR-0003), the utility tree into an
agnostic half and a coupled half (ADR-0004), the database service into a package
(ADR-0014). Measured 2026-08-14, the core package holds 1,137 Python files where
upstream's holds 537.

That is the force this record answers to. Every one of those decompositions
**deletes the file an upstream patch is written against**, and the question of
whether that is acceptable was never written down — it was settled in practice
and re-argued in review.

### Two failure shapes, and only one of them is a conflict

Attempted 2026-08-14 in a scratch worktree: of the twenty most recent upstream
commits touching the core package, **none applies cleanly**. Inspecting the
failures separates two kinds:

| shape | git status | meaning |
|---|---|---|
| both modified | `UU` | an ordinary content conflict — resolvable, in principle, by reading both sides |
| deleted by us | `DU` | the patch has **no landing site**: the file it modifies does not exist here |

The second shape is the argument. It is not a conflict a careful merger resolves;
there is nothing to resolve, because the target is gone. Upstream's
odoo/orm/models.py, odoo/orm/registry.py and odoo/tools/sql.py — deliberately
not backticked, since none of those paths exists in this tree — became
`odoo/orm/models/`, `odoo/orm/runtime/` and `odoo/libs/sql/`, each a package
whose modules divide the original's responsibilities differently.

Widening the sample: across the fifty most recent upstream commits touching the
core, they modify 65 core Python files, of which **20 are absent from
`19.0-marin`**, and **14 of the 50 commits touch at least one file with no
landing site** (measured 2026-08-14).

So mergeability was not traded away at the margin. It was spent, in full, by the
records listed above, and the loss is structural rather than incidental.

## Decision

**`19.0-marin` carries no backward-compatibility obligation to upstream, and
nothing is merged or cherry-picked from `19.0`.**

- **`19.0` is a read-only mirror**, kept in sync with upstream and never carrying
  fork work. Its purpose is to be *read*: a clean reference to diff against and
  to source fixes from.
- **A useful upstream fix is re-implemented by hand**, against this tree's
  structure, with its own test, landing as ordinary work under the ordinary
  review rules. It is not imported — and it is not found for free: judging a
  given upstream commit useful, inapplicable, or already superseded by fork work
  is per-commit reading, and there is no shortcut that does it in bulk.
- **Mergeability is not a design constraint.** A refactor is judged on
  correctness, performance and clarity. It is not narrowed, deferred or blocked
  to keep a merge cheap, because there is no merge for it to be cheap for.

Three objections follow from a premise this record rejects, and are therefore
**void rather than outweighed**. They may not be raised to block or narrow a
change, and may not be accepted from a reviewer:

> *"this complicates the upstream merge"* · *"upstream does it this way"* ·
> *"this increases divergence"*

The costs that do count are unchanged and are the only ones: behavioural
regressions, test breakage, and migration for stored data.

This restates in decision form what `doc/coding_guidelines.rst`'s *Scope and
precedence* already asserts as a rule. The guide says what the rule is; this
record says why it is sound and what was given up for it.

## Alternatives considered

**Keep the fork mergeable — constrain refactors to preserve upstream's file
layout and public names.** This is the option that had to lose for the fork to
do its principal work: it forbids ADR-0001, ADR-0003, ADR-0004 and ADR-0014
outright, since each is precisely a change of layout. It is also no longer
available. A constraint of this kind must be adopted before the divergence, not
after; measured 2026-08-14, twenty of twenty upstream core commits already fail
to apply, so adopting it now would pay the full cost of the restriction and
recover none of the benefit.

**Rebase onto upstream periodically instead of merging.** Rejected: a rebase
replays the fork's commits over a moved base, so every fork commit that touches a
decomposed file hits the same missing-target problem — this is the merge problem
multiplied by the commit count, not divided by it. It also rewrites a shared
branch's history, which §12 of the workspace instructions forbids for a checkout
several sessions work at once.

**Vendor upstream as a subtree or submodule and layer the fork's changes on
top.** Rejected because the changes are not additive. A layering model requires
the base to stay the base; the decompositions *move* upstream's code out of the
files it shipped in, so there is no layer that expresses them — the "layer" would
be a near-complete rewrite of the vendored tree.

**Automate selective tracking with a path-mapping importer** — teach a tool that
upstream's `sql_db.py` is this tree's `odoo/db/`, and redirect hunks. Rejected
because the mapping is not a function. That one module became a package whose
modules divide its responsibilities by concern, so *which* module an upstream
hunk belongs in is a judgement about the change's meaning. Making that judgement
is re-implementation — with the tests omitted and the reasoning hidden inside a
tool.

**Leave it unwritten.** This is the state that held until this record, and it is
why the record exists. The understanding was real but not citable, so it was
re-argued: the workspace instructions had to name the three objections above
verbatim and declare them void, which is what a rule looks like when it has no
argument to point at. An unwritten premise is re-litigated by every new
contributor, and by every reader — human or otherwise — whose prior knowledge is
of upstream rather than of this tree.

## Consequences

- **Structural work is judged on its merits.** The largest records in this
  register exist only under this decision; without it each would have been
  narrowed to preserve a merge that was never going to happen.
- **Every upstream commit to the core becomes a triage decision, and the queue is
  unbounded.** The cost is not "re-implement the fixes we want", which understates
  it by assuming someone already knows which those are. It is that each upstream
  commit touching the core has to be read and classified — not applicable,
  already superseded by fork work, or worth adapting — and only the last of those
  three ends in code. Measured 2026-08-14, 281 upstream commits had touched the
  core package since the merge base: 255 excluding translation churn, of which
  196 were tagged `[FIX]`, and none of the 281 carried a recorded triage
  decision. There is no automation, no feed and no alert, and nothing
  distinguishes a commit that was read and dismissed from one nobody opened.
  This is the principal cost of the decision; it is paid per commit rather than
  per fix, and this record accepts it without discharging it.
- **A security fix upstream is not a security fix here until someone carries it
  across.** That follows from the bullet above rather than adding to it, and it
  is the sharpest edge of this decision: the backlog is not uniformly low-stakes,
  and its `[FIX]` majority is where the stakes sit.
- **The mirror must keep fetching.** Diffing against `19.0` is the only remaining
  benefit of tracking upstream at all, and it is lost silently if the branch goes
  stale — the failure would look like an absence of findings, not an error.
- **The gap widens monotonically.** Re-implementation gets harder as the two
  trees share less vocabulary. Nothing bounds this, and no decision here
  pretends to.
- **Recollection describes upstream, not this tree.** Reviewers and language
  models both carry knowledge of stock Odoo, and under this decision that
  knowledge is a hazard rather than a shortcut. The guidelines already say to
  trust the repository over training data, and Appendix A — the fork's field
  renames, whose upstream spellings no longer resolve — is what that hazard
  looks like once it has cost somebody an afternoon.

## Enforcement

**No checker, and the reason is worth stating.** The invariant is "no history
from `19.0` reaches `19.0-marin`", which is a property of the commit graph rather
than of the tree, and the gates in `tooling/architecture/` all read the tree. It
is held by branch discipline instead: work lands on `19.0-marin` by pull request,
and `19.0` is written to only by syncing upstream.

The shape a gate would take, should it ever be needed, is a check that no commit
reachable from `19.0-marin` has an ancestor on `19.0` beyond the merge base — one
`git merge-base --is-ancestor` call per merge commit. It is not written because
the failure it guards against has never occurred, and a gate with no failure to
its name is a gate nobody maintains.

The second half of the decision — that the three objections are void — is a
review rule, and is stated as one in `doc/coding_guidelines.rst`.
