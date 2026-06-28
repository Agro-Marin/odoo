# ADR-0010: Consolidate the internal cache/compute access surfaces around `env._core`

- **Status:** Accepted (steps 1–3 implemented; step 4 dropped on reassessment; step 5 deferred)
- **Date:** 2026-06-26

## Context

The two pure-engine objects from ADR-0002 — the per-transaction `FieldCache`
and `ComputeEngine` — are today reachable through **four** different handles.
This is an *internal* concern, distinct from the addon-facing façade boundary
of ADR-0008 (`odoo.addons` → `odoo.orm`); here the question is how *framework
code* reaches the cache and the compute engine.

| Handle | Level | Used by | Live? |
|---|---|---|---|
| `env._core` (`OrmCore`, `components/core.py`) | id-level façade | framework ORM code (~29 call sites; `get_field_data` dominates) | **yes, growing** |
| `transaction.cache_store` / `transaction.compute_engine` | raw objects | `Transaction` internals (`clear`, building `core`) | public, but **~0 external readers** (the only non-test hits are docstrings) |
| `env.cache` (`cache_compat.Cache`) | recordset-level wrapper | addons: `contains`/`get_records`/`get_values`/`update`/`update_raw`/`set` (~16 sites across account/hr/sale/calendar) + `check()` in tests | legacy, still patched (`ad0f7064d72` added `update_raw`) |
| `env`'s recompute/protect adapters (`is_protected`, `add_to_compute`, `protecting`, `records_to_compute`, …) | recordset-level | framework code holding recordsets | yes |

Two observations shape this decision:

1. **This is not a performance question.** The hot read path
   (`Field.__get__`) inlines its own memo
   (`env.__dict__["_field_cache_memo"][self]`) and only falls through to
   `env._core` on a per-`(field, env)` memo *miss*, which is then memoised. So
   `OrmCore` is essentially never on the per-record path; the cost of the façade
   is a handful of frames amortised to near-zero. Any "collapse" is justified by
   clarity and maintenance, **not** speed. (An earlier framing of this finding
   leaned on a perf argument; measurement refuted it.)

2. **The team is investing *into* `OrmCore`, not away from it.**
   `616425a2efc` routed recompute-scheduler construction through
   `OrmCore.new_scheduler` specifically so model code stops reaching
   `core.engine` directly. The trajectory is "`env._core` is the one sanctioned
   id-level handle," and `OrmCore`'s own docstring states it is a *curated*
   surface, not a complete mirror.

The real friction is therefore narrower than "four surfaces":

- `OrmCore` is a **curated subset** (read + schedule + protect). Mutation
  (`set_value`, `invalidate_field`, `invalidate_all`) and lifecycle (`clear`,
  `prune_empty`) are deliberately *not* on it — they belong to `Transaction`
  (lifecycle) and to `env.cache` / the field-level helpers (recordset-level).
  That is defensible, but it is undocumented, so the façade reads as
  "accidentally incomplete" rather than "intentionally curated."
- The ~25 hand-written pass-throughs can silently **drift** from the underlying
  `FieldCache`/`ComputeEngine` (a typo'd delegation, or an underlying rename),
  with nothing to catch it. (`clear_cache` and `new_scheduler` already diverge
  from the "same name and contract" claim in the docstring.)
- `transaction.cache_store` / `compute_engine` are **public attributes with no
  external readers** — they leak the implementation and suggest a third "right
  way" to reach the engine that nobody actually needs.
- `env.cache` is a genuinely *separate*, legacy, recordset-level wrapper still
  used by addons; its deprecation docstring was corrected in `5f67e3aa069`.

## Decision

Keep `OrmCore` as the internal id-level boundary and reduce the surrounding
noise, rather than collapsing or removing the façade.

1. **Affirm `env._core` as the single id-level access point.** Document in
   `OrmCore`'s module docstring (and `odoo/ARCHITECTURE.md`) that it is an
   *intentionally curated* subset: reads, dirty/patch tracking, scheduling and
   protection live here; cache *mutation* and *lifecycle* do not, by design.

2. **Privatise the raw handles.** Rename `Transaction.cache_store` →
   `_cache_store` and `compute_engine` → `_compute_engine`. They are
   implementation detail of the transaction with ~0 external readers; the
   rename is a few internal references plus one test. This removes a whole
   public surface at near-zero cost and makes "reach the engine via `env._core`"
   the only sanctioned path.

3. **Guard the façade against drift.** Add a unit test that, for each
   `OrmCore` pass-through, asserts it delegates to the identically-named
   `FieldCache`/`ComputeEngine` method (a mock records the call). This catches a
   typo'd or stale delegation cheaply and lets the curated surface grow safely —
   turning "triple-maintenance risk" into a one-line test assertion per method.

4. **Phase out `env.cache` (`cache_compat.Cache`) — separately and later.**
   *(Reassessed during implementation and **dropped** — see Implementation
   status. `env.cache` is the recordset-level cache API, not redundant with the
   id-level `env._core`, and the `env._core` migration target was wrong.)*
   ~~Migrate the ~16 addon call sites to `env._core` (+ field-level
   helpers/`browse`) one method-family at a time, then delete the wrapper,
   keeping only `check()` (the test cache-vs-DB consistency check) under a
   clearly test-only home. This is addon-touching and larger; it is *not*
   bundled with steps 1–3.~~

5. **Leave the recordset-level recompute/protect adapters on `env`.** They are a
   different abstraction level (recordset-aware, for callers that hold a
   recordset rather than ids) and are correct where they are. Grouping them
   under an `env.recompute` helper is possible but cosmetic and low-value;
   out of scope.

## Alternatives considered

- **Delete `OrmCore`; expose `env._cache` / `env._engine` directly.** Smallest
  long-term surface and zero pass-through maintenance, and `FieldCache` /
  `ComputeEngine` are already cohesive, well-named APIs. Rejected as the primary
  path because it contradicts the team's active investment in `OrmCore` as the
  boundary (`616425a2efc`), would churn ~29 call sites for no functional gain,
  and trades a curated id-level surface for direct coupling to the engines' full
  (including internal) APIs. Worth revisiting only if the façade's curation
  benefit fails to materialise.
- **`OrmCore.__getattr__` delegating proxy** (drop the hand-written twins).
  Removes the maintenance but loses the typed/IDE-visible surface and the
  curation, and is fragile if cache and engine ever share a method name.
  Rejected.
- **Status quo.** The façade works and has no bugs; the cost is ongoing
  ambiguity ("which handle?") and silent-drift risk. Steps 1–3 buy most of the
  clarity for little cost, so doing nothing under-invests.

## Consequences

- One fewer public way to reach the engines (`cache_store`/`compute_engine`
  become private); `env._core` is unambiguously *the* id-level handle, and its
  curation is documented intent rather than apparent accident.
- The façade can grow a method only when production genuinely needs one, with a
  test that guarantees the delegation is faithful — drift becomes a failing
  test, not a latent bug.
- No behavioural or performance change from steps 1–3; the migration in step 4
  is the only part that touches addon code, and it is incremental and
  independently shippable.
- The "two real objects, many handles" smell is reduced to: `env._core`
  (id-level, framework) and `env.cache` (recordset-level, legacy, shrinking),
  plus the recordset adapters at their own abstraction level.

## Migration plan

1. **Steps 1–3 (one PR, framework-only, low-risk):** document the curated
   contract; rename the raw handles to `_`-private and fix the internal
   references + the one test reader; add the delegation drift-guard test.
   Validate with `test_orm` + the `profiler` suite (the latter exercises
   `OrmCore` scheduling) + `base`.
2. **Step 4 (phased, per method-family):** for each of
   `contains`/`get_records`/`get_values`/`update`/`update_raw`/`set`, migrate
   its addon call sites to `env._core` equivalents, shrinking
   `cache_compat.Cache`; when only `check()` remains, relocate it to a test-only
   module and delete the wrapper. Each family is its own PR, validated against
   the owning addons' test suites.
3. **Optional later:** group `env`'s recompute/protect adapters under
   `env.recompute` if a future change makes the grouping pay for itself.

## Risks & validation

- *Privatising the raw handles* could miss a reflective/string-based access.
  Mitigation: grep confirms ~0 non-test readers; CI `test_orm` + `base` cover
  the transaction lifecycle (`clear`, `invalidate`).
- *The `env.cache` migration* is the only addon-touching risk and is precisely
  why it is phased and gated per addon test suite rather than done in one sweep.
- This ADR records a *proposal*; it is not enforced until accepted and steps
  1–3 land.

## Enforcement

Steps 1–3, once landed, are guarded by the new `OrmCore` delegation test and by
the standing `test_orm` / `base` gates (ADR-0007). A `layer_check.py` contract
forbidding `_cache_store` / `_compute_engine` access outside
`runtime/transaction.py` and `components/` could be added (ADR-0005 style) if
the convention proves insufficient; the underscore-private naming is the
lighter first step.

## Implementation status

- **Steps 1–3: done.** `OrmCore` / `Environment._core` docstrings and
  `ARCHITECTURE.md` document the curated boundary (step 1);
  `Transaction.cache_store` / `compute_engine` are now `_cache_store` /
  `_compute_engine`, with the single external reader (an account test) moved to
  `env._core` (step 2); `TestOrmCoreDelegationDrift` in
  `components/tests/test_core.py` asserts every pass-through delegates to its
  same-named `FieldCache` / `ComputeEngine` method, plus a guard that the table
  stays complete as `OrmCore` evolves (step 3). Validated: component suite +
  `test_orm` (876) + `profiler` (9).
- **Step 4 (retire `env.cache`): dropped after reassessment.** Implementing
  steps 1–3 made clear that `env.cache` is *not* redundant legacy: it is the
  **recordset-level** cache API — a thin, context-aware wrapper over the
  field-level cache helpers (`field._get_cache` / `field._update_cache`) — at a
  different abstraction level from the now-private, **id-level** `env._core`.
  The proposed migration target was wrong: a mechanical `env._core` rewrite of
  the call sites would mishandle context-dependent fields (whose raw cache is
  `{cache_key: {id: value}}`, not `{id: value}`) and would couple addon code to
  private field helpers, and some consumers live outside this repo
  (`enterprise`/`agromarin`). `env.cache` is therefore **kept** as the
  sanctioned recordset-level cache API; its docstring was corrected to stop
  pointing callers at `env._core`. (Genuinely shrinking it would mean
  eliminating addon cache-poking as an anti-pattern — a separate, larger
  business-logic effort, not a handle swap.)
- **Step 5 (group `env` recompute/protect adapters): not started** — optional,
  cosmetic.
