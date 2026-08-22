# ADR-0009: Close the enforcement loop (mainline gating, full façade scope, true floors)

- **Status:** Accepted
- **Date:** 2026-06-25
- **Extends:** ADR-0005 (CI boundary enforcement), ADR-0006 (drift-zero
  ratchet), ADR-0008 (façade boundary). None are reversed; this removes three
  gaps that let their guarantees be bypassed.

## Context

An audit of the *wiring* behind ADRs 0005–0008 found three measured gaps.

1. **The gates were `pull_request`-only.** No workflow carried `push:` on the
   protected branches, so a commit landing directly on `19.0-marin` — or a PR
   merged stale against an updated base — was never re-checked. Measured on a
   clean `19.0-marin` HEAD with the pinned tools (mypy 1.19.1, ruff 0.15.2):
   **mypy 2074 against a committed floor of 1972 (+102)**, **ruff 686 against
   658 (+28)**. Those regressions landed on mainline via direct ORM-refactor
   commits and nothing caught them — ADR-0006's "a baseline nothing enforces is
   a comment", re-introduced at the trigger.

2. **The façade contract scanned one of two addon trees.** ADR-0008 wired
   `facade-boundary` to `source=("odoo.addons",)`, which maps to
   `odoo/addons/`. The sibling `addons/` tree (7,829 `.py` files, mounted at
   `odoo.addons.*` by the addons-path loader) was never scanned and held 7 live
   violations: `from odoo.orm._typing import ValuesType` across
   `addons/resource/models/`.

3. **`architecture.yml` could not fire on addon-only changes.** Its `paths:`
   filter listed `odoo/orm|db|libs` only, so a PR adding an `odoo.orm.*` import
   in addon code skipped the gate entirely.

## Decision

1. **Re-verify mainline.** Add `push: branches: ['19.0-marin', '19.0']`, no
   path filter, to every blocking gate: `architecture`, `ruff`, `py_typecheck`,
   `typecheck`, `lint`, `unit_tests`, `integration_tests`, `rust`.

2. **Widen the façade contract.** Set the source to
   `("odoo.addons", "addons")`, and add `odoo/addons/**` and `addons/**` to
   `architecture.yml`'s `paths:`. Route the 7 `resource` violations through
   `odoo.models`, which exports `ValuesType`. That took the checker to 6,069
   files on 2026-06-25; still seconds.

3. **Make the floors true.**
   - **ruff 658 → 633.** Safe autofixes first (I001, UP037, RUF100,
     PLR1716/1730, UP034) across 45 files: 686 → 633, **25 below the prior
     floor**. The DB-free unit tiers (471 tests) stayed green, all changed files
     byte-compile, none is a package `__init__` or registration module.
   - **mypy 1972 → 2074**, the honest clean-HEAD count. The +102 is
     overwhelmingly `[attr-defined]` from model mixins reaching through
     `BaseModel`'s shared `_fields`/cache core — structural debt for the
     encapsulation work, not blanket `# type: ignore`, which the ratchet would
     wrongly reward for lack of a suppression counter-gate.

## Consequences

- From this commit the floors can only fall, on PRs **and** on mainline.
- A new `odoo.orm.*` import in either addon tree fails CI, including on a PR
  touching addon code alone and on a direct mainline push.
- The mypy floor is higher but real, and is a standing invitation to the
  encapsulation work (a field-cache accessor object; breaking the Cache↔Write
  mixin cycle). Re-baselining up is a one-time correction: the `push` gate makes
  a silent re-baseline impossible.
- Deliberately not done here, tracked separately: a `# type: ignore` / `# noqa`
  counter-ratchet, `warn_unused_ignores = True`, mypy scope over the façade
  packages, CODEOWNERS protection on `tooling/ratchet/baselines/`.

## Enforcement

`.github/workflows/*.yml` (`push:` on protected branches),
`tooling/architecture/layer_check.py` (widened `facade-boundary` source),
`tooling/ratchet/baselines/{ruff,mypy}.json` (true floors).
`tooling/architecture/test_layer_check.py` and the standing
`test_framework_core_has_no_new_violations` guard keep it honest. On the day
this landed, `layer_check.py --check` reported 0 new violations across all 6,069
scanned files; run the checker for the live verdict and file count.

## Amendments

### 2026-08-07 — the scanned-file count is dated, not current

Two sentences gave 6,069 files in the present tense. The measurement was right
on 2026-06-25 and is part of the record; presenting it as today's number is this
record's own failure mode one level up. Both now name the date. The mypy and
ruff counts elsewhere are left alone: they are explicitly measurements of a
named commit, which is what makes the argument.
