# ADR-0072: The cross-repo gate checks names, not only modules

- **Status:** Accepted
- **Date:** 2026-08-28

## Context

ADR-0031 split "a symbol a consumer imports must still exist" into two gates and
gave the reason in its own *Alternatives considered*:

> **One gate for both.** Rejected because the analyses do not overlap: one asks
> whether a *file* still exists and must reach across repository boundaries at
> push time; the other asks whether a *name* is still exported and is answerable
> inside one repository at CI time.

The second clause is false, and the counterexample is the shape ADR-0031 was
written about. On 2026-08-27 a community commit renamed the exported
`resequence` to `resequenceRecords` in
`addons/web/static/src/model/relational_model/resequence.js` and updated every
community consumer. `enterprise/web_map` still imported the old name. Asking
whether that import is satisfied needs the export from **this** repository and
the import from **another**: it is not answerable inside one repository, and the
`resequence`/`resequenceRecords` pair is a name, not a file, so neither existing
gate could see it.

What each gate did see:

- `named_export_coherence.py` reads names, and reads them correctly — it reports
  the finding the moment a checkout has both trees. Community CI checks out this
  repository alone, so on the PR that caused the break it had no enterprise to
  read.
- `cross_repo_coherence.py` reaches across repositories at push time, which is
  where both trees sit — and asked only whether a *file* was removed.
  `relational_model.js` was still there, so it printed
  `No dangling cross-repo imports. Coherent. ✓` for the commit that killed
  the web asset bundle.

The cost was the failure mode ADR-0031 opens with, and larger than a red gate:
an unsatisfied named import is a link-time error, so the whole web asset bundle
refused to build for **every** database with enterprise installed. Every backend page
returned a `QWebError`, and the only visible symptom in the suite was a browser
tour reporting that it was never ready — a failure that reads as flakiness and
was, for a while, attributed to the addons path rather than to a broken bundle.

## Decision

**The push-time cross-repo gate checks removed names as well as removed
modules.** `cross_repo_coherence.py` gains a second half: for the core client
modules the pushed range *modified*, it reads every consumer's named imports of
those specifiers and reports the ones the module no longer exports.

The two halves keep their separate analyses — one over
`--diff-filter=DR`, one over `--diff-filter=M` — and share the place they run,
because the place is what both need and what neither had alone.

The name half borrows `named_export_coherence`'s parser and export resolver
rather than re-deriving them. Two readings of what a module exports drift apart,
and the one that is wrong is the one nobody runs; a re-export chain resolved by
one and not the other is a false positive in a pre-push hook, which is how a
hook gets uninstalled.

Range-scoping is deliberate. The gate speaks for the push in front of it, so it
does not fail a developer for drift that arrived on the branch some other way;
`named_export_coherence` in the sibling repositories' own workflows remains the
sweep that catches the rest.

## Alternatives considered

**Check out the sibling repositories in community CI.** This is the fix that
puts the failure on the PR that causes it, and it stays blocked for the reason
ADR-0009 records: this repository is public and `enterprise` is private under a
different owner, so the checkout needs a cross-owner credential that a public
repository's workflows — including workflows on forks — would carry. That is a
security decision, not a wiring change, and it is not made here.

**Schedule the sibling workflows.** A cron in each sibling would shorten the
window from "the next sibling PR" to "the next tick" with no new credential. It
narrows the window; it does not close it, and it still reports after the push.
Worth doing, and not a substitute for the gate: kept as a follow-up rather than
folded in here to look like a fix.

**Run the whole `named_export_coherence` sweep in the hook.** It is the cheapest
gate in the tree and would catch drift regardless of who caused it. Rejected for
the asymmetry it creates at the prompt: a push blocked by a name some other
commit broke is a push the developer cannot fix, and a gate that blocks on other
people's debt is one people learn to bypass. The sweep belongs where a red
result has an owner.

**Leave it to review.** Refuted by the incident: the rename commit updated every
consumer it could see, and the one it could not see was in another repository
that no reviewer of that PR had checked out.

## Consequences

- The commit that renames a core export and misses a sibling is stopped at the
  push, naming the consumer file, line, specifier and the missing name.
- `cross_repo_coherence.py` now depends on `named_export_coherence`, which
  already imports it for consumer discovery. The import is function-local and
  says why; a module-level one is a cycle.
- The hook's weakness is unchanged and still the honest limit of this design: a
  clone that never ran `tooling/install-hooks.sh` has no hook, so this is a
  guard rail on the machine that installed it, not a property of the branch.
  ADR-0031 stated that plainly and it is restated rather than quietly inherited.
- Nothing about ADR-0031's whole-module analysis changes. It is superseded for
  its claim that the two questions do not overlap, not for what it built.

## Enforcement

`tooling/architecture/test_cross_repo_coherence.py` covers the name half against
fixture repositories: a rename the consumer missed, an aliased import (which
must be read on the *imported* side — reading the local name is what would have
made this very incident invisible, since it aliased the removed `resequence`
**to** the name that still exists), a consumer renamed in step, a re-export
chain, and a module the range did not touch. The `--check` exit code covers both
halves.

The gate runs as a `pre-push` hook via `.pre-commit-config.yaml`
(`cross-repo-coherence`), installed by `tooling/install-hooks.sh`.
