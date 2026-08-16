# ADR-0020: Declare the client's public surface — the set, the entry point, and the override points

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records decisions already enforced)

## Context

The Python core has a declared public surface: the façades, each with an
explicit `__all__`, enforced against every addon (ADR-0008). Behind it the core
is free to move, and ADR-0001's decompositions were affordable because of it.

**The client had no equivalent.** Every file under `addons/web/static/src` is
reachable as a `@web/...` specifier, so "what `web` publishes" was the same set
as "what `web` contains". When the surface was first measured, 327 distinct
specifiers were imported from outside the addon and 276 of them reached three or
more segments deep — into a module's internals rather than at a layer's edge.

The cost was paid, in full, before any of this was written down. Relocating the
misfiled half of one directory cost 338 downstream edits; dissolving the rest cost
roughly 500 more. Those edits span four separately-versioned repositories that
cannot be committed atomically, so each move is a sequencing problem rather than
a refactor. **None of that expense came from the refactor being wrong.** It came
from there being no boundary between what `web` publishes and what it merely
contains — the exact condition ADR-0008 removed on the Python side, left standing
on the larger of the two trees.

Three distinct things were unpinned, and they fail in different ways.

**Which modules may be reached.** Nothing recorded the set, so it grew by
accident: an import written in another repository is a unilateral addition to
`web`'s obligations, made by someone who never opened `web`.

**Where a directory may be entered.** A commit gave 37 directories a *face* — a
sibling module (`addons/web/static/src/views/pivot.js` beside
`addons/web/static/src/views/pivot/`) publishing what the directory offers — and
cut the surface from 327 to 223. It did not make the face load-bearing. Nothing
stopped a sibling repo importing past it, and a face nobody has to use is an
alias, not a boundary.

**Which methods may be overridden.** A module surface guarantees that
`@web/views/form` keeps existing. It says nothing about whether `FormController`
keeps having the method a downstream addon overrides. That contract was tested
rather than argued: two identically-configured worktrees, differing only by
renaming one such method inside `web` while leaving its nineteen downstream
overriders untouched, produced *identical* results — same suite outcome, and the
typecheck ratchet sitting exactly on its committed floor. Nothing in the
toolchain noticed that nineteen overrides had stopped overriding anything. No
gate models class inheritance, so the method-level contract was pinned by
nothing at all.

## Decision

**`web` publishes a surface, it is declared in the tree, and it is pinned at
each of the three levels it exists at.** A second addon (`mail`) is governed the
same way through the same gates, parameterised rather than forked.

### 1. The set — which specifiers outsiders may import

Pinned in a per-addon file (`tooling/architecture/public_surface_web.txt`,
`tooling/architecture/public_surface_mail.txt`) and held **shrink-only**: the
surface may narrow freely, and may not grow without the pin being updated in the
same change. Production and test-only reach are pinned together and reported
apart, because moving a file breaks a suite exactly as thoroughly as it breaks a
feature, while only the first is a statement about what `web` owes anyone.

The pin is a worklist, not an achievement. It records the surface we have, so
that narrowing it is a measurable act rather than a hope.

### 2. The entry point — where a faced directory may be entered

A surface specifier must land **at** a face, never reach past one into the
directory behind it. This is a rule about *shape*, and it is why the set pin does
not already cover it: adding one deep import to the pin file is a legal edit
there, indistinguishable from any other growth, so the set gate records that
breach rather than refusing it. The two compose — the pin says what may be
reached, this says where it may be entered.

**Scope is from outside the addon only.** Inside it, one module reaching a
neighbour's internals is a layering question and belongs to ADR-0019's gates. A
face is a statement to *other addons*, and that is the only direction it
constrains.

### 3. The override points — which members downstream may extend

The method-level contract — what a downstream addon may override by subclass or
by patch and expect the base to call — is enumerated and pinned, with the live
figures kept in the gate's own `MEASURED` block rather than restated in prose;
`doc_measured.py` regenerates it and the gate fails when the block and the tree
disagree. That mechanism exists because the first draft of that gate hardcoded
five counts and three were stale within the hour.

### Pin what already holds, while it still holds

Every one of these was introduced against a tree that already satisfied it — the
faces in particular were measured at zero violations before the gate landed.
Enforcing an invariant that already holds costs one file and breaks nothing, and
that is the cheapest it will ever be. The alternative is to discover later that
some number of breaches accumulated, at which point each one is a cross-repo
negotiation — which is precisely the 327-specifier history above.

## Alternatives considered

**Declare an explicit API — an index module per layer, everything else private.**
The Python answer (ADR-0008), and the right end state. Rejected *as the first
step*: it requires deciding what the API is for 327 specifiers reached from four
repositories, and until the surface is measured and shrinking, that decision
would be made blind. The pin is the instrument that makes the API decision
possible later; it is not a substitute for it.

**Let the set pin carry the whole job.** Rejected because a set cannot express a
shape. A new deep import into a faced directory grows the pin by one line and
reads exactly like legitimate growth, so the boundary that faces were created to
establish would erode one legal edit at a time.

**Rely on the typecheck and test suites to catch broken overrides.** Rejected on
evidence, not on principle: the renaming experiment above left both green. An
override that silently stops overriding produces no type error and no test
failure, because the base class simply stops calling it.

**Govern only `web`, and treat `mail` as an addon like any other.** Rejected —
`mail` has the same property and the second-largest client tree in the repo, with
its own sizeable reach from outside. Extending the gates by parameter rather than
by fork is the pattern already used elsewhere in this directory, and it is what
keeps one rule from becoming two that drift.

## Consequences

- Internal moves inside `web` become priceable before they are attempted, rather
  than discovered as downstream breakage across repositories that cannot be
  committed atomically.
- **Growth is now deliberate.** Adding a specifier to the surface means editing a
  pin in this repository, so an import written in a sibling repo can no longer
  enlarge `web`'s obligations unilaterally and silently.
- The cost is a pin file that must be updated in the same change as the code, and
  a reviewer who understands that a growing pin is a decision rather than a
  formality. A pin nobody reads becomes a rubber stamp; that risk is real and is
  not mechanically preventable.
- The override contract is enumerated but not yet *narrowed*. Knowing what
  downstream depends on is a precondition for reducing it, and this record buys
  the first, not the second.
- Faces are load-bearing, so adding a directory to the faced set is now a
  commitment rather than a convenience.
- What remains unpinned is named rather than implied: the private-member coupling
  *inside* `web`, and the patch mechanism's own reliability, each have a gate and
  neither has a record. They are separate arguments and want separate records.

## Enforcement

Three gates in `tooling/architecture/`, each declaring `ADR = "0020"`, all run by
`.github/workflows/architecture.yml`:

| gate | pins |
|---|---|
| `tooling/architecture/js_public_surface.py` | the set of externally-reached specifiers, shrink-only, per addon |
| `tooling/architecture/js_face_boundary.py` | that a surface specifier lands at a face, never past it |
| `tooling/architecture/js_extension_surface.py` | the method-level override contract, against its `MEASURED` block |

`tooling/architecture/test_gate_adr_coverage.py` checks that citation resolves to
this record and that this record is `Accepted`. For each gate's live figures, run
it — this record does not restate them.
