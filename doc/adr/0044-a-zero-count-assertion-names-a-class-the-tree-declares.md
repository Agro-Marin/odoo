# ADR-0044: A zero-count assertion names a class the tree declares

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

`expect(".o_thing").toHaveCount(0)` is how a HOOT test says *this must not be
rendered*. It is also the only assertion shape a **wrong selector cannot be
distinguished from a passing test**. A positive count fails the moment a class is
renamed; a zero count starts passing for the wrong reason and never stops.

Three instances in this fork, none of which found each other:

- **`marketing_automation`.** Its "Remove activity" test asserted on
  `.fa-trash`. `83cf923c4d7` (FontAwesome 4 → 7) rewrote the markup to
  `fa-trash-can` and left the selector strings alone. The suite was bundled into
  the web unit-test asset bundle and selected by no runner, so nothing reported
  it. Closing that is why `enterprise`'s
  `.github/workflows/integration_tests.yml` exists — and it fixed the module,
  not the class of defect.
- **`industry_fsm_sale`.** The same rename, the other direction: `4af1869b2c3`
  renamed the icon in `product`'s `order_line.xml`, and the test asserting on it
  lives in `enterprise`. It stayed red from 2026-03-06 to 2026-08-17 — five
  months — because the assertion crosses a repo boundary no lane runs both sides
  of. A *positive* count, so it did fail loudly; it failed where nobody was
  listening.
- **`timesheet_grid`.** `expect(".btn_timer_line.fa-stop-danger").toHaveCount(0)`.
  No markup has ever carried `fa-stop-danger` — the button renders `fa-stop` and
  `btn-danger` as separate classes — so the assertion was not stale, it was born
  vacuous, three lines below two assertions using the correct
  `.btn_timer_line.btn-danger`.

Different causes, one shape: **a selector naming a class the tree does not
have.** Two needed a suite run to expose, one of those a suite run that does not
exist. The third needed nothing but a reader, and got none.

## Decision

A zero-count HOOT assertion must name CSS classes the tree declares somewhere
outside its tests. `tooling/architecture/js_vacuous_assertions.py` measures the
violations and `tooling/ratchet/baselines/jsvacuous.json` floors them.

"Declares" is deliberately weak: the class appears as a word in any non-test
`.js`, `.xml`, `.scss` or `.css` under the scanned roots. A static scan cannot
prove a selector matches at runtime, and trying would produce a gate nobody
trusts. What it *can* decide is whether the tree has ever heard of the class,
which is the property all three incidents violate.

Two exemptions, both necessary:

- **Composed classes.** `o_field_daterange` is never written down;
  `getFieldClass` concatenates `o_field_` with the widget name. A declared prefix
  ending in a separator exempts what it composes. The prefix must be specific
  past the namespace — `o_` is itself a token in this tree, falling out of any
  `` `o_${x}` `` template literal, and honouring it exempted every `o_*` class
  there is. The gate read a confident **0** against a tree with two dozen real
  findings until that was fixed.
- **Fixture classes.** A test may render its own markup (`o_test_action`) and
  then assert it is gone. Such a class is absent from the tree by design, so a
  class occurring in the test file beyond its zero-count selectors is treated as
  declared by that file.

Scope is `o_`, `o-`, `oi-` and `fa-`: the namespaces this project owns or vendors
and spells out. Bootstrap ships classes the tree never writes down, so requiring
a local declaration for them would report noise.

## Alternatives considered

**Resolve the selector against rendered DOM instead of source text.** What a
suite run does, and strictly better where it applies. It requires the suite to
run, which is what was missing in two of the three incidents — a gate that
presupposes the thing that was absent buys nothing.

**Ban zero-count assertions outright** in favour of asserting the positive
state. Wrong: "this is not rendered" is a real property, and the tests asserting
it are mostly correct. Removing the shape deletes working tests to close a hole
in a minority of them.

**Fix the two dozen findings and add no gate.** What happened to
`marketing_automation`: one instance fixed, the class untouched, two more found
months later by different routes. The fix and the floor are the same change
precisely so the third route does not need finding.

**Require the class to appear in the same addon.** Too strict: `enterprise`
tests assert on markup that `odoo` renders — the `industry_fsm_sale` case — and
scoping per addon would report every one as a violation.

## Consequences

- The floor is the debt, not the target. It starts at the count measured the day
  this landed and moves one way; each entry is a test asserting something about
  markup that does not exist, and finding out what it *meant* to assert is
  per-test work.
- This does not replace running the suites. It decides one decidable half — the
  class the tree never had — and leaves the class the tree *renamed* to the lanes
  that execute tests. Both `industry_fsm_sale` and `marketing_automation` are in
  that second half, and a static gate would have caught neither. It catches the
  third kind and makes it unable to accumulate while the other two are addressed
  by widening what CI runs.
- The measurement is per-root, so `enterprise` can be scanned by its own
  cross-repo lane on the same script without a second copy of the gate — the
  pattern `named_export_coherence.py` already uses.

## Enforcement

`tooling/architecture/js_vacuous_assertions.py`, floored by
`tooling/ratchet/baselines/jsvacuous.json` and run as a blocking step of
`.github/workflows/architecture.yml`. Exact mode, so removing a vacuous
assertion without lowering the floor fails as loudly as adding one.

Not enforced: that a declared class is the *right* class, or that the selector
matches at runtime. Those need the suites executed. `odoo` runs no HOOT lane
today and `enterprise` runs one for `marketing_automation` and its siblings, so
the majority of both trees' JS suites are checked by nothing. This gate is
deliberately the decidable part and is not a substitute for that lane.
