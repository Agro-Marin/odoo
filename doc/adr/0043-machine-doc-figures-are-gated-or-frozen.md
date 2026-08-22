# ADR-0043: A machine-doc figure is gated or frozen, never bare

- **Status:** Accepted
- **Date:** 2026-08-16

## Context

`machine_doc_v*/` directories carry the machine-readable map of a module —
routes, models, architecture, conventions, test tags. `CLAUDE.md` makes them the
**first** thing read before touching a module, ahead of its README: spend a
small, accurate amount of context instead of a large, exploratory one.

That also decides who is harmed by a wrong number. A human skimming a stale count
discounts it; an agent loading it adopts it as a **premise** and builds on it.
The audience that makes these documents worth writing is the audience least able
to notice when they are wrong, so a wrong figure here is worse than no figure.

Four modules ship a `factcheck.sh` harness for exactly this. They were correct
and wired to nothing, so they ran when someone remembered. What accumulated:

- **`addons/web`** — seven defects. The harness caught two the moment it ran;
  the other five were outside what it checked. A reference to a since-dissolved
  addons/web/doc directory (unbackticked here for the reason this record is
  about) sat in two documents, invisible because the cited-path scan did not look
  inside a backticked *command*.
- **`addons/website`** — its root was the literal
  `/home/marin/Odoo/addons/odoo/addons/website`, a path present in no checkout.
  Every path-based assertion resolved against nothing: 42 failures, 1 pass. A
  three-line change deriving the root from `BASH_SOURCE` took it to 45/0.
- **`addons/mail`** — 22 red, because its expectations are literals
  (`assert_eq <measured> 31` against a real 32). The script is a second copy of
  the tree, so the tree moving is indistinguishable from the docs being wrong.

The instinct this raises is to stop stating numbers at all. **The failure data
does not support it.** Of the seven defects in `web`, only two were drift. Three
were wrong on the day they were written — including a profiler stack whose every
frame was off by one (CDP reports `CallFrame.lineNumber` 0-based; the profile was
transcribed raw) and a coverage figure, `756 of 763`, whose numerator and
denominator came from different trees and which therefore described no tree that
has ever existed. Numbers that were never right are not fixed by having fewer
numbers; they are fixed by measuring them.

The tree also contains something close to a controlled comparison. The same
quantity — `@ts-check` coverage of `addons/web` — is stated in two documents in
one directory. `addons/web/machine_doc_v1/ARCHITECTURE.md`'s copy is derived by
the harness and tracked a 758 → 763 change correctly. The restatement in
`addons/web/machine_doc_v1/EXTENSION_ARCHITECTURE_REVIEW.md` was wrong through
eight revisions, sat in a section titled *Survived unchanged*, and called itself
*exact*. Same fact, same week, same directory. Only the measured one survived.

## Decision

**Every figure in a machine doc is one of two things, and a figure that is
neither is a defect.**

- **Gated.** Derived from the tree by the module's `factcheck.sh` and asserted
  against the document (`assert_doc_cites`), never held as a literal in the
  script. The measurement lives once; the digits stay inside the sentence. The
  default for anything cheap to re-derive.

  The rule covers **measurements, not invariants**.
  `assert_eq "$(grep -c 'export class Foo' …)" "1"` is right as it stands — the
  literal *is* the claim, and it should fail the day the symbol is renamed. The
  test is whether ordinary growth moves the number.
- **Frozen.** Explicitly pinned to a base commit, for figures that *cannot* be
  re-derived — a reading from an ad-hoc scanner, a profile, a benchmark. The
  document names the base, and the figure is not "corrected" to a current value,
  because doing so silently restates the argument built on it.

Two corollaries, both learned above:

1. **A harness derives its roots from `BASH_SOURCE`.** A literal path validates
   the tree it was written on, or no tree at all.
2. **Every restatement is pinned, not just the first.** One fact stated in six
   places has six owners and therefore none.

**The harnesses run in CI, blocking** — `.github/workflows/machine_doc.yml`. It
**discovers** harnesses rather than enumerating them, so a machine doc cannot
join the tree with a broken harness unnoticed. Known-red harnesses sit in an
explicit `QUARANTINE` with a written reason, checked in **both** directions: a
quarantined harness that starts passing also fails the lane, so the list cannot
outlive the breakage it documents.

No ratchet. A factcheck assertion is not debt to ramp down: it either describes
the tree or it does not, and since every expected value is derived, a passing run
costs nothing to keep passing.

## Alternatives considered

**Drop numbers from machine docs entirely.** Rejected on the evidence: it
addresses two of seven observed defects, and removes what makes the documents
worth reading — "763 files, 2 untyped" states a posture a paragraph cannot.

**Ratchet the failures, as with `ruff` and `tsc`.** Those gates ratchet a
population of findings that shrinks over time. A factcheck assertion is a binary
claim about the tree, and a floor above zero would mean "some of this map is
knowingly wrong" — the state that makes an agent's first read unsafe.

**Warn-only during adoption.** Rejected for the reason
`addons/web/machine_doc_v1/JSDOC_TYPE_TIGHTENING.md` records for the typecheck
lane: a warn-only gate is read as noise and then not read. Quarantine names what
is broken; `continue-on-error` hides it.

## Consequences

- Adding a figure means adding its assertion, or naming its base. That is the
  cost, and it is the point.
- A single-repo CI checkout cannot judge fork-wide claims: no workflow passes
  `repository:` to `actions/checkout`, so the sibling checkouts are absent and
  those assertions SKIP **with a count** rather than fail. Cross-repo coverage
  belongs to the sibling repos' own workflows.
- **An allowance for "cannot decide" needs a floor, or it becomes an allowance
  for "did not look".** The first version of that skip let a *misresolved root*
  — a checkout whose directory is not named `odoo`, so nothing indexes — pass
  with 565 references silently unjudged, where the previous behaviour failed
  loudly. The harness now refuses to report at all unless the tree under test is
  itself in the index. Undecidable and unexamined must not share an exit.
- `mail` is quarantined at adoption. Leaving the list means converting its
  literals to the derive-and-cite form, not bumping them.
- Four modules carry a harness; four more machine docs (`odoo/tests`,
  `odoo/addons/base`, `addons/gamification`, `addons/base_automation`) carry
  none, so their figures are held by nothing. The lane discovers harnesses, not
  machine docs, so this is a gap it reports by silence.

## Enforcement

`.github/workflows/machine_doc.yml`, blocking on every PR and on pushes to the
protected branches. It discovers `addons/**/machine_doc_v*/factcheck.sh` rather
than listing them, fails if discovery finds nothing, fails on any
non-quarantined harness that fails, and fails on any quarantined harness that
**passes**.

The rule's text is `doc/coding_guidelines.rst` §1.4. What the lane cannot check
is whether a figure carrying no assertion *should* have one — a document stating
a bare number that no assertion mentions is invisible to it. That is a review
responsibility, and the reason §1.4 is written as a rule rather than left to the
gate.
