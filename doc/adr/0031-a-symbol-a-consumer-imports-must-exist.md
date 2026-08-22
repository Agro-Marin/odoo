# ADR-0031: A symbol a consumer imports must still exist — including across repositories

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records decisions already enforced)

## Context

Under native ESM an import that does not resolve is not a soft failure. A named
import the target module does not export is a **link-time error**: the browser
refuses the whole module graph, so the entire asset bundle dies for every
database that installs the importing module.

**And no test catches it**, because no test file gets to run. The suite reports
fewer tests than it should, which reads as green — ADR-0023's silent shape,
through a different door.

Two removals produce it, needing different analyses.

**A module disappears while a sibling repository still imports it.** The removal
and the paired consumer-side change live in two separately versioned
repositories that cannot be committed atomically, so no single-repo gate sees
the pair. A recorded incident: core dropped two client modules that a sibling's
studio module, seven uploaders and a viewer widget all imported, and a
`git pull` of core alone left that checkout importing modules that no longer
existed.

**A named export disappears from a module that still exists.** The whole-module
gate is blind to this by construction. The motivating incident was a rename
inside a view module while two downstream addons still imported the old names:
both *files* existed, so the cross-repo check saw nothing, and every suite in the
addon failed to boot.

## Decision

**Two gates, because the two removals are different questions.**

### Whole modules, checked across repositories, before the push

For the commits being pushed, the gate finds client modules deleted or renamed
away, maps each to its specifier, drops any specifier still provided by another
core file — an explicit re-home annotation, or a file still at the derived path —
and greps every configured sibling consumer for a **runtime** import of what
remains.

Type-only references do not count. Imports are collected with the same
comment-stripping parser the layering gates use, so a documentation reference
never trips it.

**It runs as a pre-push hook, and that placement is the decision.** The sibling
repositories' own workflows provide a post-hoc backstop, but only the hook stops
the push itself — and once core is pushed the sibling checkouts are already
broken for everyone who pulls.

**The hook's weakness is stated rather than hidden**: a declaration installs
nothing, and a clone that never ran the installer has no hook, so this gate does
not run there. A guard rail on the machine that has it, not a property of the
branch.

### Named exports, checked inside this repository

Every `import { x }` finds an `x`. Both source and test trees are scanned: the
same broken import in a test file kills the test bundle with the identical
silent symptom.

## Alternatives considered

**One gate for both.** Rejected because the analyses do not overlap: one asks
whether a *file* still exists and must reach across repository boundaries at
push time; the other asks whether a *name* is still exported and is answerable
inside one repository at CI time.

**Rely on CI in the sibling repositories.** That backstop exists and is
insufficient alone: it reports the breakage *after* core has been pushed, at
which point every consumer's pull is broken and the fix is a cross-repo
sequencing problem rather than an edit.

**Rely on the test suites.** Refuted by the failure mode: a module graph that
refuses to link runs no tests, so the suite reports fewer tests rather than
failures.

**Make it CI on core instead of a hook.** Core's CI cannot see the sibling
checkouts — it checks out this repository alone, the constraint ADR-0009 records
for the façade scope. The hook runs where the checkouts sit side by side.

**Require atomic cross-repo commits.** Not available: the repositories are
separately versioned by design (ADR-0018), and no mechanism commits across them.

## Consequences

- The failure mode where a whole asset bundle dies for every database — with a
  green-looking suite — is caught at the push that would cause it, for the clone
  that installed the hook.
- **Coverage is uneven and depends on a local installation step.** A contributor
  who never ran the installer gets no protection and no warning that they have
  none. Named here so nobody reads the gate as a branch-level guarantee.
- Removing a client module from core means checking the configured siblings,
  which makes deletion more expensive.
- The named-export gate scans tests as well as source, so a rename must be
  carried through test files in the same change.
- Neither gate covers the reverse direction: a sibling that removes something
  core imports. Core does not import from siblings, so the asymmetry is
  structural — but it is an assumption worth stating.

## Enforcement

Two gates in `tooling/architecture/`, each declaring `ADR = "0031"`:

| gate | holds | where it runs |
|---|---|---|
| `tooling/architecture/cross_repo_coherence.py` | a removed client module is not still imported by a configured sibling | pre-push hook, installed by `tooling/install-hooks.sh` |
| `tooling/architecture/named_export_coherence.py` | every named import resolves to an actual export, in source and tests | `.github/workflows/architecture.yml` |

`tooling/architecture/test_gate_adr_coverage.py` checks that both citations
resolve to this record and that it is `Accepted`.
