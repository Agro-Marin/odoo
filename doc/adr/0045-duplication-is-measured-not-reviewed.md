# ADR-0045: Duplication is measured, not reviewed

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

`tooling/architecture/` holds eighteen gates over this tree's JavaScript. Every
one asks a question about a block *in place* — is this import legal, is this
member private, does this service return an instance.

**None of them can see that the block exists twice.** A copied block is
structurally identical to a block that belongs where it is: it imports legally,
respects the layer, touches no foreign private. So duplication is the one
property always left to review, and review is what it defeats — the two copies
are rarely in the same diff, and after the second lands nothing points at the
first.

An audit of `addons/web/static/src` on 2026-08-17 found, none of it visible to
any lane:

- **The JS error beacon existed twice**, in `addons/web/static/src/module_loader.js`
  and `addons/web/static/src/core/errors/error_beacon.js`, with byte-identical
  `hashCode` (8 lines), `elideNested` (6) and `serializeCause` (31). The copies
  had diverged in the parts nobody pinned: one capped the message at 4096
  characters and the other did not, and they kept **two dedup sets**, so one
  error crossing the boot boundary was beaconed twice.
- **One `supportedOptions` descriptor was written out twelve times** across ten
  files. Three carried the `help`; nine did not, so the same option under the
  same label showed a tooltip on Char and none on Email. The label itself had
  forked into two `.pot` msgids differing only in case.
- **A subtle fix existed in four places.** `_editHandover` — the mechanism
  `addons/web/machine_doc_v1/LIST_EDIT_RENDER_COST.md` exists to explain — was
  written out in both `DynamicList` and `StaticList`, each of which also carried
  an inline second copy. All four look right in isolation; only a render-budget
  test tells a broken one from a working one.

The `mail` beacon copy is the instructive case. A test file *said* the two copies
must agree and claimed to pin it. Mutating the canonical `serializeCause` turned
7 tests red — that half worked. Mutating the canonical `hashCode` to a different
algorithm left **all 28 green**, because the test named after it never reached
the canonical copy. Hand-written parity is not a substitute for not having two
copies, and it is not even reliable evidence that you have checked.

The fork's posture already implies this gate: *Scope and precedence* in
`doc/coding_guidelines.rst` makes naming standardisation instrumental —
canonical names exist so redundancy becomes **detectable**, `_get_x_vals` and
`_build_x_vals` normalising to one name *being* the duplicate report. That
programme had no instrument. This is it.

## Decision

`tooling/architecture/js_duplication.py` counts **duplicated significant lines
between two files** in a governed addon's `static/src`, and
`tooling/ratchet/baselines/jsduplication.json` floors the total.

Three load-bearing choices.

**Byte-exact, not window-hashed.** The obvious implementation hashes fixed
windows of normalised lines and sums the hits. It scores a *prefix* relationship
as duplication. Measured on `calendar_year_renderer.js` against
`calendar_common_renderer.js`, a window detector reported 89 duplicated lines
across five methods; byte-level extraction showed exactly one method (9 lines)
was a duplicate and the other four were prefixes — the year renderer's body was
the *head* of the common one's. A gate must report the number it can defend. The
audit that produced this record published the 89 before catching it.

**Normalisation stays shallow.** Blank and comment-only lines are dropped and
whitespace runs collapse, so reindenting cannot hide a block — but renaming a
variable can. Deliberate: a ratchet that under-reports is a floor that still only
moves down; one that cries wolf gets a `# noqa` culture around it. Token- or
AST-level matching is the obvious extension and is not needed to start.

**Nine significant lines is the floor for a run.** Below that the matches are
idiom — an import block, a three-line guard, a `return {` header — and nine is
the shortest run in this tree that survived a manual read as *should have been
shared*.

The gate indexes windows before comparing, so only file pairs that can possibly
share a run are compared. Naively quadratic it is 298k pairs and 78 seconds;
indexed it is 0.3 seconds — the difference between a gate CI runs on every PR
and one nobody enables.

## Alternatives considered

**Leave it to review.** The status quo, and the reason the four instances above
exist. Two copies are rarely in the same diff, and after the second lands nothing
points at the first — the failure mode, not a risk of it.

**Pin each duplication by hand, with a parity test.** Tried, for the beacon, and
the *weakest* option rather than a cheaper one: mutating the canonical
`serializeCause` turned 7 tests red while mutating the canonical `hashCode` left
all 28 green. A hand-written parity suite is a second copy of the argument and
drifts like any other.

**A general-purpose copy-paste detector** (jscpd and friends). Rejected on
reporting, not capability: they score prefix relationships as duplicates and
report token-level near-matches, both producing findings a reviewer has to argue
down. A ratchet whose findings are argued down stops being read.

**Hold it at zero rather than ratchet it.** Some runs are irreducible — an
identical import block between two siblings is what sharing looks like — so a
zero would be bought with suppressions, and a suppression list is the
hand-maintained roster this fork keeps replacing with derivations.

## Consequences

- A copied block costs ratchet budget in the PR that lands it, rather than being
  found by an audit two years later.
- The floor moves down as extraction happens and cannot move up silently. As
  with every `exact` ratchet, lowering it also fails the build until the new
  floor is committed, so an extraction has to state what it removed.
- **A high number is not by itself a defect report.** Some runs are irreducible.
  The gate measures the class; a human decides which instances are worth
  extracting. That is why it is ratcheted rather than held at zero.
- Onboarding a second tree copies the `--addon` pattern: one script, one flag,
  its own baseline.
- Renaming while copying still evades it. If that becomes the observed dodge,
  the answer is token-level matching in this same gate, not a second one.

## Enforcement

`tooling/architecture/js_duplication.py`, run by
`.github/workflows/architecture.yml` and floored by
`tooling/ratchet/baselines/jsduplication.json` in the default `exact` mode.

`tooling/architecture/test_js_duplication.py` pins what the gate must and must
not call a duplicate — identical bodies, the prefix case, a divergence
mid-block, the run floor, reindentation, and the documented blind spot for
renames. It also pins that the candidate-pair pruning changes no answer, because
that optimisation is the difference between 0.3s and 78s and one that quietly
drops findings is worse than a slow gate.

`test_every_gate_refuses_an_empty_tree.py` covers it too: pointed at a tree with
no files the gate raises rather than reporting zero, because a ratchet that reads
0 from a bad path banks a floor nothing can exceed.
