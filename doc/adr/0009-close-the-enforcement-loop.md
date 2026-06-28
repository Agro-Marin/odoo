# ADR-0009: Close the enforcement loop (mainline gating, full façade scope, true floors)

- **Status:** Accepted
- **Date:** 2026-06-25
- **Extends:** ADR-0005 (CI boundary enforcement), ADR-0006 (drift-zero ratchet),
  ADR-0008 (façade boundary). None are reversed; this ADR removes three gaps that
  let their guarantees be bypassed in practice.

## Context

ADRs 0005–0008 built a strong enforcement story — an AST layer checker, a
drift-zero ratchet, a façade contract — but an audit of the *wiring* found the
loop was not actually closed. Three concrete, measured gaps:

1. **The gates were `pull_request`-only.** Every workflow under
   `.github/workflows/` triggered on `pull_request` and nothing else — no `push:`
   on the protected branches. So a commit landing directly on `19.0-marin`
   (or a PR that merged stale against an updated base) was **never re-checked**.
   The ratchet floor became fiction: measured on a clean `19.0-marin` HEAD with
   the pinned tools (mypy 1.19.1, ruff 0.15.2), **mypy was 2074 vs. a committed
   floor of 1972 (+102)** and **ruff was 686 vs. 658 (+28)** — regressions that
   landed on mainline via direct ORM-refactor commits and that *nothing caught*.
   This is precisely the "a baseline nothing enforces is a comment" failure
   ADR-0006 set out to kill, re-introduced one level up (at the trigger).

2. **The façade contract scanned only one of two addon trees.** ADR-0008 wired
   `facade-boundary` to `source=("odoo.addons",)`, which `layer_check.py` maps to
   `odoo/addons/`. But this checkout has a **second** addon tree — the sibling
   `addons/` (7,829 `.py` files, the bundled business modules, mounted at
   `odoo.addons.*` at runtime by the addons-path loader). It was never scanned,
   and it contained **7 live runtime violations**:
   `from odoo.orm._typing import ValuesType` across `addons/resource/models/*.py`
   (a name the façades already re-export). ADR-0008's "the promise is now true and
   stays true" held only for the framework tree.

3. **`architecture.yml` could not fire on addon-only changes.** Its `paths:`
   filter listed `odoo/orm|db|libs` only, so a PR that introduced an
   `odoo.orm.*` import in addon code touched no triggering path and skipped the
   gate entirely.

## Decision

1. **Re-verify mainline.** Add `push: branches: ['19.0-marin', '19.0']` (no path
   filter) to every blocking gate: `architecture`, `ruff`, `py_typecheck`,
   `typecheck`, `lint`, `unit_tests`, `integration_tests`, `rust`. Mainline is now
   re-checked in full on every push; drift cannot accumulate unobserved.

2. **Widen the façade contract to all addon code.** Set the `facade-boundary`
   source to `("odoo.addons", "addons")` so **both** trees are scanned, and add
   `odoo/addons/**` and `addons/**` to `architecture.yml`'s `paths:`. Pay down the
   7 `resource` violations by routing them through `odoo.models` (which exports
   `ValuesType`). The checker now walks 6,069 files; still seconds.

3. **Make the floors true.** Re-baseline to the measured clean-HEAD counts so the
   ratchet enforces from a real number going forward:
   - **ruff 658 → 633.** First applied ruff's *safe* autofixes (I001 import-sort,
     UP037, RUF100 unused-`noqa`, PLR1716/1730, UP034) across 45 files — 686 → 633,
     i.e. **25 below the prior floor**, a net improvement locked in. The DB-free
     unit tiers (471 tests) stayed green; all changed files byte-compile; none are
     package `__init__`/registration.
   - **mypy 1972 → 2074**, the honest clean-HEAD count. The +102 is overwhelmingly
     `[attr-defined]` from model mixins reaching through `BaseModel`'s shared
     `_fields`/cache core — structural debt whose paydown belongs with the
     field-cache/mixin **encapsulation** work, *not* blanket `# type: ignore`
     (which the ratchet, lacking a suppression counter-gate, would wrongly reward).

## Consequences

- The drift-zero promise is now operative on the branch it protects: from this
  commit the floors can only fall, on PRs **and** on mainline.
- A new `odoo.orm.*` import in *any* addon — either tree — fails CI, on a PR that
  touches only addon code as well as on a direct mainline push.
- The mypy floor is higher but **real**. It is a standing invitation to the
  encapsulation work (give the field-cache an accessor object; break the
  Cache↔Write mixin cycle), which should drive `[attr-defined]` — and the floor —
  down. Re-baselining up is a one-time correction, not a habit: the `push` gate
  now makes a *silent* re-baseline impossible.
- Follow-ups this ADR deliberately does **not** do (tracked separately): a
  `# type: ignore` / `# noqa` counter-ratchet (so suppressions can't game the
  count), `warn_unused_ignores = True`, extending mypy scope to the façade
  packages, and CODEOWNERS protection on `tooling/ratchet/baselines/`.

## Enforcement

`.github/workflows/*.yml` (`push:` on protected branches) +
`tooling/architecture/layer_check.py` (`facade-boundary` source widened) +
`tooling/ratchet/baselines/{ruff,mypy}.json` (true floors). The layer checker's
own suite (`tooling/architecture/test_layer_check.py`) and the standing
`test_framework_core_has_no_new_violations` guard keep it honest; `layer_check.py
--check` reports 0 new violations across all 6,069 scanned files.
