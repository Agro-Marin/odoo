# ADR-0027: A forced render is not a stronger render — it hides unsubscribed reads

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records a decision already enforced)

## Context

Forcing a render re-renders a component **and its whole subtree**,
unconditionally. It reads as a stronger version of an ordinary render. It is a
different operation, with two costs that are easy to miss and one that is
expensive to find.

**It defeats prop diffing.** A row component can document its props as
per-render invalidation keys, so that diffing skips the row when they are all
identical. A forced render walks past that and re-renders every row regardless.

**It hides unsubscribed reads, which is why this is a correctness rule and not a
performance preference.** While a blanket forced render was installed for every
view, a component could read state it had never subscribed to and still appear
correct, because something re-rendered it anyway. Removing the blanket in
2026-08-09 surfaced exactly that: a hook built a value as a getter closed over
state that could never subscribe during render, and four view controllers never
wrapped their model in reactive state at all, so their template reads subscribed
nothing.

Neither was visible while the force was papering over it, and **no other gate
can reach them**: both are questions about what a component *subscribed to*,
which no import-graph or export-surface check can answer.

**A third failure mode is worth naming because it cost the most to find.** A
forced render fires the will-update-props hook on children *even when their props
are identical*, so derived state rebuilt inside that hook silently depends on the
force. One renderer's derived parameters did exactly that, and subscribing the
renderer without noticing left it rendering fresh output from stale mappings —
**50 tests failed with no exception raised.**

## Decision

**No forced render in the client's core source, except at a site pinned with a
reason.**

The pinned list is the mechanism that makes the rule usable: a forced render is
occasionally the honest answer, and each such site is recorded with why, so the
next reader gets the argument rather than an unexplained exception. Anything not
on the list fails.

Scope is the core client source. The gate's sibling scope — forced renders
elsewhere in the addon trees — is ratcheted rather than drift-zero, because that
code was not written under this rule and holding it at zero on day one would
have meant either a large unrelated refactor or a list of exceptions long enough
to be meaningless.

## Alternatives considered

**Treat it as a performance lint.** This is the reading the rule most invites,
and it is wrong in the direction that matters: the three failures above are
correctness failures — state read without subscription, and derived state
computed from stale inputs — that happened to be masked by a mechanism people
thought of as an optimisation. A performance framing would have made every one of
them a low-priority finding.

**Remove the ability to force a render.** Rejected: there are legitimate sites,
and the pinned list exists to hold them. A rule with no escape hatch gets worked
around in ways that are harder to see than the thing it forbade.

**Fix the unsubscribed reads and leave the mechanism alone.** This is what
removing the blanket did, and it is not sufficient on its own. The blanket was
removed once; nothing stopped the next component from forcing a render and
re-acquiring the same blindness locally. The gate is what makes the fix stay
fixed.

**Rely on the test suite.** The suite is what eventually failed — 50 tests, no
exception, from a renderer producing fresh output from stale mappings. A failure
with no exception and no obvious cause is the most expensive kind to diagnose,
and it is exactly what an unsubscribed read produces.

## Consequences

- A component that needs a value must subscribe to it, and the failure to do so
  surfaces as a broken render rather than as a render that happens to be correct
  because something else forced it.
- **Adding a forced render now costs an argument**, written at the site. That is
  the intent: the sites that remain are the ones somebody defended.
- Prop diffing means what it says, so a component documenting invalidation keys
  can rely on them.
- The rule does not detect an unsubscribed read directly — it removes the
  mechanism that hides one. A component that reads unsubscribed state and is
  never re-rendered at all still fails silently, and nothing here catches that.
- The two scopes differ in strictness, which is a deliberate staging rather than
  an inconsistency: drift-zero where the code was written under the rule, a
  ratchet where it was not.

## Enforcement

One gate in `tooling/architecture/`, declaring `ADR = "0027"`, run by
`.github/workflows/architecture.yml`:

| gate | holds |
|---|---|
| `tooling/architecture/js_forced_render.py` | no forced render outside the pinned sites in core client source; a ratcheted budget elsewhere |

`tooling/architecture/test_gate_adr_coverage.py` checks that the citation
resolves to this record and that it is `Accepted`. For the gate's live figures,
run it — this record does not restate them.
