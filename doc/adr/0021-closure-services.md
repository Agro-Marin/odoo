# ADR-0021: A service's own callers go through its facade, and its facade should be an instance

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records decisions already enforced)

## Context

Odoo services are overwhelmingly written as a closure that returns an object
literal — roughly 35 of the 38 in `addons/web/static/src` when this was measured.
A service declares helpers as local functions, registers some of them with other
services, and returns a literal naming the ones it publishes.

That shape has two independent failure modes, and every other gate in
`tooling/architecture/` is structurally blind to both.

**The routing failure: a patch that applies to some callers and silently skips
others.** A downstream addon extends a closure service the only way a closure
allows — by patching `start` and mutating the object it returned. That reaches
anyone who goes through the service facade. It does *not* reach the service's own
internal registrations, which captured the *function object* during the original
`start()`, before the patch ran.

This is not hypothetical. A sibling repository's portal webclient patches the
command service to neutralize the command palette for portal users, who "can not
have access to some of its features (searching users, menus, ...)". The direct
calls are blocked; **the keyboard shortcut still opens the palette**, because the
service had registered the hotkey against its closure identifier rather than
against the facade. Reproduced in a real browser against the real service on
2026-08-03. No error is raised. The patch looks like it worked.

**The shape failure: the only seam is `start` as a whole.** When `start()`
returns a literal, a downstream addon that wants to change one helper must
re-run the entire body and then mutate what came back — in one case 403 lines it
must now own forever, upstream fixes to them included. When `start()` returns an
instance, the same intent is one line against the prototype, and it composes with
other patches through `super`.

**Why no existing gate sees either.** The blindness is structural, not an
oversight: the surface and named-export gates reason about *module* exports, and
this is one function calling another in the same scope — no export, no import, no
edge. The import-graph gates (ADR-0019) never see it for the same reason. The
function-length gate measures how long `start` is, not who it calls. And ESLint
has no rule, because calling a sibling closure is ordinary, correct JavaScript
everywhere except inside a patchable service facade.

The property none of them holds is that **a service's own callers see the same
implementation its consumers do.**

## Decision

Two gates for the two halves, because they fail independently and are fixable
independently.

### 1. Routing is drift-zero: internal callers go through the facade

For any service registered in the services registry, a name the service
publishes must not also be reached directly by the service's own code. A patch
then either reaches every caller or it does not apply at all — the silent partial
application above becomes impossible rather than merely discouraged.

This half is cheap: it is a change to how a service calls itself, not to what it
is, so it did not wait on the larger rewrite.

### 2. Shape is a shrinking budget: a service hands back an instance

The literal-shaped services are counted and the count may only fall, floored in
`tooling/ratchet/baselines/jsserviceshape.json`; `mail` carries its own budget in
`tooling/ratchet/baselines/jsserviceshape_mail.json` — the same script under
`--addon`, not a fork.

**The property is a prototype seam, not a line count.** This distinction was
learned the expensive way and is why the first draft of this gate was scrapped.
A 549-line closure in the list view is *fine*: the renderer's prototype delegates
into it in both directions, and 88 downstream addons extend logic living inside
it. A gate keyed on size would have flagged the module's best-extended code.
Four shapes hold a seam and all four are in this tree — own it as a class,
delegate to it, inherit it through mixins, or instantiate it — and the
literal-shaped services use none of them.

**The budget counts literal-shaped services, not oversized ones.** A budget of
oversized `start()` bodies falls when someone extracts helpers out of one, which
moves the number without adding a seam: the metric improving while the thing it
measures does not. Counting shape can only fall when a service genuinely gains a
prototype. Line counts are still reported, because they are the right *order* to
do the work in, but they are not the budget.

**Undecidable shapes are reported apart and not counted.** A few services return
something the analysis cannot follow — a conditional, an imported factory — and a
case the tool cannot decide is not evidence of a defect.

### The scope limit is stated, not hidden

Both gates cover **services only**. The equivalent question for hooks cannot be
decided from the hook's own file, because the seam lives in the *consumer* that
delegates to it; proving a hook unseamed would need a whole-program search
neither gate attempts. Services are enumerable, self-contained, and the systemic
case.

## Alternatives considered

**Rewrite every closure service to a class now, and skip the gates.** Rejected on
sequencing, not on merit — it is the end state. The routing defect is live, has a
reproduced user-visible symptom, and is fixable without touching a service's
shape; making its fix wait on a thirty-five-service rewrite would leave a
shipped, silent misbehaviour in place for the duration.

**Key the shape gate on the length of `start`.** Rejected after it was built and
scrapped: it flags the best-extended code in the addon. The 549-line closure with
88 downstream extenders scores worst on size and best on the property that
actually matters, which is the clearest possible demonstration that size is the
wrong proxy.

**Budget only the oversized literals.** Rejected because the metric would improve
without the architecture improving — extracting helpers lowers the count and adds
no seam. A budget whose number can fall for the wrong reason teaches people to
move the number.

**Count the undecidable shapes as violations.** Rejected. A gate that reports
what it cannot determine as a defect trains reviewers to discount it, and a
discounted gate is the state ADR-0006 exists to end.

**Document the patch hazard and rely on review.** Rejected on evidence: the
hazard was documented nowhere and found in production behaviour, and it raises no
error by construction. A failure mode whose only symptom is "the feature the
patch was supposed to remove still works" is not one review catches.

## Consequences

- A downstream patch of a service now either reaches every caller or fails the
  gate. The class of bug where a patch appears to work and half-applies is
  closed for services.
- The shape budget can only fall by adding a real prototype seam, so progress on
  it is progress on extensibility rather than on a number.
- **The cost is real and ongoing.** Converting a literal service to an instance
  is genuine work per service, and there are dozens. The budget makes the
  remaining distance visible; it does not shorten it.
- Hooks remain ungoverned on this property, and the record says so rather than
  implying the tree is covered. Anyone reading the gate as "services and hooks"
  would be wrong.
- A second addon is governed by parameter rather than by fork, so the rule cannot
  drift into two rules.
- Extending either gate to a new tree costs a flag and a baseline, which is the
  pattern already used for the other per-addon budgets.

## Enforcement

Two gates in `tooling/architecture/`, each declaring `ADR = "0021"`, both run by
`.github/workflows/architecture.yml`:

| gate | holds |
|---|---|
| `tooling/architecture/js_patch_blind_facade.py` | drift-zero: a service's own callers reach it through its facade |
| `tooling/architecture/js_service_shape.py` | the shrinking budget of literal-shaped services, per addon |

The shape budgets are ratchet baselines, so a lowered count must be committed
with the change that lowers it. `tooling/architecture/test_gate_adr_coverage.py`
checks that both citations resolve to this record and that it is `Accepted`. For
either gate's live figures, run it — this record does not restate them.
