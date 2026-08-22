# ADR-0021: A service's own callers go through its facade, and its facade should be an instance

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records decisions already enforced)

## Context

Odoo services are overwhelmingly a closure returning an object literal — roughly
35 of the 38 in `addons/web/static/src` when measured. A service declares helpers
as local functions, registers some with other services, and returns a literal
naming the ones it publishes.

That shape has two independent failure modes, and every other gate in
`tooling/architecture/` is structurally blind to both.

**Routing: a patch that applies to some callers and silently skips others.** A
downstream addon extends a closure service the only way a closure allows — by
patching `start` and mutating the object it returned. That reaches anyone going
through the service facade. It does not reach the service's own internal
registrations, which captured the *function object* during the original
`start()`, before the patch ran.

Not hypothetical. A sibling repository's portal webclient patches the command
service to neutralize the command palette for portal users, who "can not have
access to some of its features (searching users, menus, ...)". The direct calls
are blocked; **the keyboard shortcut still opens the palette**, because the
service registered the hotkey against its closure identifier rather than against
the facade. Reproduced in a real browser against the real service on 2026-08-03.
No error is raised. The patch looks like it worked.

**Shape: the only seam is `start` as a whole.** When `start()` returns a
literal, a downstream addon wanting to change one helper must re-run the entire
body and mutate what came back — in one case 403 lines it must own forever,
upstream fixes included. When `start()` returns an instance, the same intent is
one line against the prototype, composing with other patches through `super`.

**Why no existing gate sees either.** The surface and named-export gates reason
about *module* exports, and this is one function calling another in the same
scope — no export, no import, no edge. The import-graph gates (ADR-0019) miss it
for the same reason. The function-length gate measures how long `start` is, not
who it calls. ESLint has no rule, because calling a sibling closure is ordinary,
correct JavaScript everywhere except inside a patchable service facade.

The property none of them holds: **a service's own callers see the same
implementation its consumers do.**

## Decision

Two gates for the two halves, which fail and are fixed independently.

### 1. Routing is drift-zero: internal callers go through the facade

For any service in the services registry, a name the service publishes must not
also be reached directly by the service's own code. A patch then either reaches
every caller or does not apply at all.

Cheap: a change to how a service calls itself, not to what it is, so it did not
wait on the larger rewrite.

### 2. Shape is a shrinking budget: a service hands back an instance

Literal-shaped services are counted and the count may only fall, floored in
`tooling/ratchet/baselines/jsserviceshape.json`; `mail` carries its own budget in
`tooling/ratchet/baselines/jsserviceshape_mail.json` — the same script under
`--addon`, not a fork.

**The property is a prototype seam, not a line count.** Learned the expensive
way, and why the first draft of this gate was scrapped. A 549-line closure in
the list view is fine: the renderer's prototype delegates into it in both
directions, and 88 downstream addons extend logic inside it. A gate keyed on
size would flag the module's best-extended code. Four shapes hold a seam and all
four are in this tree — own it as a class, delegate to it, inherit it through
mixins, instantiate it — and the literal-shaped services use none of them.

**The budget counts literal-shaped services, not oversized ones.** A budget of
oversized `start()` bodies falls when someone extracts helpers, which moves the
number without adding a seam. Counting shape can only fall when a service gains
a prototype. Line counts are still reported, because they are the right *order*
to do the work in, but they are not the budget.

**Undecidable shapes are reported apart and not counted.** A few services return
something the analysis cannot follow — a conditional, an imported factory — and
a case the tool cannot decide is not evidence of a defect.

### The scope limit is stated, not hidden

Both gates cover **services only**. The equivalent question for hooks cannot be
decided from the hook's own file, because the seam lives in the *consumer* that
delegates to it; proving a hook unseamed needs a whole-program search neither
gate attempts. Services are enumerable, self-contained, and the systemic case.

## Alternatives considered

**Rewrite every closure service to a class now, and skip the gates.** Rejected
on sequencing, not merit — it is the end state. The routing defect is live, has
a reproduced user-visible symptom, and is fixable without touching a service's
shape; making its fix wait on a thirty-five-service rewrite leaves a shipped
silent misbehaviour in place for the duration.

**Key the shape gate on the length of `start`.** Rejected after being built and
scrapped: it flags the best-extended code in the addon. The 549-line closure
with 88 downstream extenders scores worst on size and best on the property that
matters.

**Budget only the oversized literals.** Rejected: the metric would improve
without the architecture improving. A budget whose number can fall for the wrong
reason teaches people to move the number.

**Count the undecidable shapes as violations.** Rejected. A gate that reports
what it cannot determine as a defect trains reviewers to discount it, and a
discounted gate is the state ADR-0006 exists to end.

**Document the patch hazard and rely on review.** Rejected on evidence: the
hazard was documented nowhere and found in production behaviour, and it raises
no error by construction. A failure mode whose only symptom is "the feature the
patch was supposed to remove still works" is not one review catches.

## Consequences

- A downstream patch of a service either reaches every caller or fails the gate.
  The half-applying patch is closed for services.
- The shape budget can only fall by adding a real prototype seam, so progress on
  it is progress on extensibility rather than on a number.
- **The cost is real and ongoing.** Converting a literal service to an instance
  is genuine work per service, and there are dozens. The budget makes the
  distance visible; it does not shorten it.
- Hooks remain ungoverned on this property, and the record says so rather than
  implying coverage.
- A second addon is governed by parameter rather than fork, so the rule cannot
  drift into two rules. Extending either gate to a new tree costs a flag and a
  baseline.

## Enforcement

Two gates in `tooling/architecture/`, each declaring `ADR = "0021"`, both run by
`.github/workflows/architecture.yml`:

| gate | holds |
|---|---|
| `tooling/architecture/js_patch_blind_facade.py` | drift-zero: a service's own callers reach it through its facade |
| `tooling/architecture/js_service_shape.py` | the shrinking budget of literal-shaped services, per addon |

The shape budgets are ratchet baselines, so a lowered count must be committed
with the change that lowers it. `tooling/architecture/test_gate_adr_coverage.py`
checks that both citations resolve to this record and that it is `Accepted`. Run
either gate for its live figures.
