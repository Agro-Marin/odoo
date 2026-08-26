# ADR-0065: A test fixture is scoped to the suite that asks for it

- **Status:** Accepted
- **Date:** 2026-08-26

## Context

Hoot imports **every** test file in the unit-test bundle during collection, and
model definitions are job-scoped per test. A mock fixture written at column zero
in a `static/tests/**/*.data.js` therefore fails in both directions at once: it
runs for every suite in the bundle rather than its own addon's, and it runs
before the per-test mock server exists, so it does not reach the suite that
wrote it.

Fifty such statements were in the tree across twelve POS addons, in two shapes:

```js
PosConfig._records = PosConfig._records.map((r) => ({ ...r, module_pos_discount: true }));
patch(hootPosModels, [...hootPosModels, EventSlot]);
```

What they cost, measured per addon and scoped as CI runs them:

- **`pos_hr` sat at 12 failed / 11 passed.** `module_pos_hr` never arrived from
  its own fixture, so every `if (this.config.module_pos_hr)` branch in pos_hr's
  production patches took the upstream path and twelve assertions measured
  `point_of_sale`. `getCashierName` expected `"Employee1"` and got
  `"Administrator"` — a `res.users` name where an `hr.employee` name belonged.
- **`pos_iot_six` and `pos_restaurant_appointment` were passing without their
  fixtures at all.** Nothing had ever validated those records. Once they reached
  the mock server, one failed on a field the mock drops as an out-of-scope
  relation and the other turned out to be patching a model nobody had
  registered, so `pos_data` could not start and its suite ran with no store.
- **`pos_discount`'s three failures had been written off** as a fiscal-position
  tax bug needing an accounting investigation. They were fixture damage.

Across the twelve addons: **37 scoped failures, all of them from this one
shape.** `pos_sale`'s own docstring had already recorded the second shape as
unreliable — "whether they were registered depended on the order the test bundle
happened to evaluate its modules in" — and removed it from that addon alone,
four addons before anyone noticed it was a class of defect.

The failure is quiet in the worst way: a suite run alone passes, because with one
test file in the page collection and execution coincide closely enough for the
eager mutation to survive. It only fails in company, which reads as flakiness.

## Decision

A test fixture may not mutate another addon's mock model at module scope. It is
exported as a function and applied by the addon's own definer through
`beforeEach`:

```js
export const applyDiscountPosConfigRecords = () => { ... };

export const definePosDiscountModels = (extraModels = []) => {
    definePosModels(extraModels);
    beforeEach(applyDiscountPosConfigRecords);
};
```

`tooling/architecture/js_eager_mock_fixture.py` measures the violations and
`tooling/ratchet/baselines/jseagerfixture.json` floors them at zero.

`beforeEach` is what makes this correct, and `before` is not a substitute:
called at module scope it registers on the suite being collected — the calling
file — so the fixture reaches that addon's tests and nothing else, while a
suite-level hook mutates the parent job's definition and never reaches the mock
server at all. `pos_restaurant` reached this shape first (`57405b752fd`); the
decision is to require it rather than rediscover it per addon.

An addon composes from its POS-family **parent's** definer, not from the base:
`pos_iot_six` through `pos_iot`, `pos_urban_piper` through `pos_discount`,
`pos_self_order` through `pos_restaurant`. Two of the fifty were only exposed
once the fixture actually applied, and both were a model the addon used but
never registered — which composing from the parent supplies.

Two exemptions, both necessary:

- **Behaviour extension.** `patch(Class.prototype, {...})` and
  `patch(helperObject, {...})` compose through `super` rather than replacing
  shared state, and an addon needs the first before its models are registered.
  Only an **array** second argument — which can only be a wholesale replacement —
  is reported. Narrowing to that also stops the gate reporting `im_livechat` and
  `website` extending `mailDataHelpers`, which is the accepted pattern.
- **Own-addon mutation.** The gate resolves each name against the file's own
  imports and reports only bindings from a *different* `@addon/`. A file
  arranging its own fixtures is not leaking into anyone.

## Alternatives considered

**A fixture registry in `point_of_sale`.** Addons register their record patches
centrally; the base definer applies them. This is the bug with an extra layer:
registration is still module-scope, so every registered fixture still reaches
every suite. What makes the chosen shape correct is not where the patch is
stored but that `beforeEach` binds it to the collecting file.

**Leave it and rely on `--isolate`.** One page load per suite hides the leak
without removing it, costs a page load per suite, and does nothing for the other
half of the defect — the fixture that never reaches its own tests. `pos_hr`
failed at 12 under isolation too.

**Fix the addons and skip the gate.** Fifty violations accumulated because the
shape is the obvious thing to write and nothing said otherwise; `pos_sale` fixed
its own instance and the pattern went on spreading. A zero floor is what makes
the fifty-first not land.

## Consequences

The twelve addons carry an entrypoint each — ten of them new — and their test
files call it instead of the base `definePosModels`. That is the cost: an addon
with mock fixtures now needs a definer, and a test file that forgets to call it
gets no fixtures rather than someone else's.

Scoped runs went from 37 failures to 0 across all fifteen POS addons, with no
regressions. Cross-addon runs are unaffected and remain unscoped by design;
their failures come from foreign production `src`, not from fixtures, and are a
harness property this record does not address.

## Enforcement

`tooling/architecture/js_eager_mock_fixture.py`, floored at **0** by
`tooling/ratchet/baselines/jseagerfixture.json` and run by
`architecture.yml`. Drift-zero from the day it lands: the sweep that
accompanies this record took the tree to zero, so the floor guards new code
rather than recording debt.

The gate decides the two shapes statically, from each file's own imports, and
refuses an empty tree so a mis-pointed root reports an error rather than a
confident zero. Run against the commit before the sweep it reports 26 in `odoo`
and 24 in `enterprise` — the fifty this record is about — which is the check
that it measures the thing it claims to.

`enterprise` and `agromarin` carry no floor of their own; the script takes roots
positionally, so a sibling repo's cross-repo lane can point it at itself
(ADR-0044's arrangement) when one is wanted.
