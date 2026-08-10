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
| `env._core` (`OrmCore`, `orm/components/core.py`) | id-level façade | framework ORM code (~29 call sites; `get_field_data` dominates) | **yes, growing** |
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
   `OrmCore`'s module docstring (and `doc/architecture/ARCHITECTURE.md`) that
   it is an *intentionally curated* subset: reads, dirty/patch tracking,
   scheduling and
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
`orm/runtime/transaction.py` and `orm/components/` could be added (ADR-0005 style) if
the convention proves insufficient; the underscore-private naming is the
lighter first step.

## Implementation status

- **Steps 1–3: done.** `OrmCore` / `Environment._core` docstrings and
  `doc/architecture/ARCHITECTURE.md` document the curated boundary (step 1);
  `Transaction.cache_store` / `compute_engine` are now `_cache_store` /
  `_compute_engine`, with the single external reader (an account test) moved to
  `env._core` (step 2); `TestOrmCoreDelegationDrift` in
  `orm/components/tests/test_core.py` asserts every pass-through delegates to its
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

## Amendments

Append-only. An amendment corrects what this record says *about the repo*; it
never edits the decision above.

### 2026-08-07 — step 1's artefact was deleted, and step 2 was not true when it shipped

The Implementation status above reports "Steps 1–3: done." Two of the three need
qualifying; step 3 is intact and doing its job.

- **Step 1's deliverable no longer exists.** The step was "document in `OrmCore`'s
  module docstring that it is an *intentionally curated* subset". That ~30-line
  docstring was removed by the comment/docstring strip of `odoo/`
  (`eff67f80316`, 936 files, −49,443 lines). The strip was deliberate and kept an
  explicit retention list of machine-checked docstrings — `orm/__init__.py`,
  service/db.py (deliberately not backticked: real at the time, a flat file
  packagized away the next day by ADR-0014's `6920d626b7a`), all of
  `odoo/cli/` and others — but `orm/components/core.py` was
  not on it, because nothing read it. That is the lesson worth keeping: a
  docstring nominated as an ADR deliverable and gated by nothing is not a
  deliverable. `doc/architecture/ARCHITECTURE.md` still carries the
  curated-boundary statement, so the decision survives in prose; the
  class-level comment in
  `orm/components/core.py` now carries the rest.

- **Step 2 was incomplete on the day it landed.** Renaming
  `Transaction.cache_store` → `_cache_store` did not privatise the raw handles,
  because `OrmCore`'s own slots were named `cache` and `engine` — so
  `env._core.cache` *was* `transaction._cache_store`, a public pass-through
  straight to the object the façade exists to wrap. Measured when this was found:
  62 of 64 `_core.<attr>` accesses used a curated method and 2 reached the raw
  cache, both for `get_value`, which the façade did not expose. The slots are now
  `_cache` / `_engine`, `get_value` is on the façade, and
  `orm/tests/test_orm_core_facade_boundary.py` pins it.

Both corrections were found by reading the tree, not the record. The general
point is ADR-0008's, turned inward: a documented guarantee that no gate enforces
decays into a claim, and this ADR made two of them.

### 2026-08-07 — the architecture front door moved to `doc/architecture/`

This record cited the front door at the path it held inside the core package
until 2026-08-07 (odoo/ARCHITECTURE.md — deliberately not backticked, because a
backticked path in this repo asserts that the file exists, and this one no
longer does). That page sat inside the core *package* while describing the
whole repository — the gate
catalog it indexes covers `addons/**` JS and the repo-wide `eslint`/`tsc`
ratchets — so it was filed one level below its own scope, and the two halves of
the architecture document cited each other across directories. Widening
`doc_link_gate.py` to the set found 15 broken references held together by
nothing. The set is now one flat directory, `doc/architecture/`, with the front
door at `doc/architecture/ARCHITECTURE.md`.

Corrected in place: the three pointers naming the page that carries the curated-boundary
statement. It is a citation, not the decision.

### 2026-08-08 — this record's own prose still says "legacy", and the tree copied it

Step 4's reassessment (above) concluded that `env.cache` is **not** redundant
legacy and kept it as the sanctioned recordset-level cache API. Three earlier
lines of this record disagree, and they are still there, because an ADR is
append-only: the handle table in *Context* (`legacy, still patched`), the bullet
below it (`a genuinely *separate*, legacy, recordset-level wrapper`), and
*Consequences* (`env.cache` (recordset-level, legacy, shrinking)). All three were
written before the reassessment. They are correct as a record of what was
believed then and wrong as a description of the repo now — which is exactly what
this Amendments section exists to fix, so this is that fix rather than an edit.

**The tree copied the wrong half.** `doc/architecture/module.md` read "and
`env.cache` is the legacy recordset-level wrapper (ADR-0010)" until 2026-08-08 —
sourced from *Context*, citing this ADR, and contradicted by this ADR's own
Implementation status. An audit of the core package reported it as an unresolved
question (is it the supported addon API, or legacy with no deprecation path and
15 live call sites?); the answer was already here, one section further down.

**And the correction this record credits itself with was deleted.** The
Implementation status says `env.cache`'s "docstring was corrected to stop
pointing callers at `env._core`". `cache_compat.Cache` had no docstring at all
by 2026-08-08: `eff67f80316` stripped it, the same commit and the same reason as
step 1's deliverable in the amendment above — nothing read it. That is twice in
one ADR, which stops being a coincidence and becomes the finding: **every
deliverable of this record that was a docstring has been deleted, and only the
ones with tests survived.**

Closed as follows, without reopening the decision:

- `doc/architecture/module.md` states the relationship instead of the label, and says where the
  label came from.
- `cache_compat.Cache` carries the docstring again.
- `orm/tests/test_recordset_cache_levels.py` (named
  orm/tests/test_cache_compat_is_not_legacy.py at the time, deliberately not
  backticked; renamed by `e7822f78404`, see the 2026-08-09 amendment) reads
  all three: that the class
  documents itself, that `doc/architecture/module.md` does not carry the label back, that nothing
  marks the class deprecated, and — the property the decision actually rests on —
  that `Cache` methods still take recordsets while `OrmCore`'s take a field and a
  raw id. If those levels ever converge the retire-vs-keep question genuinely
  reopens, and that needs a superseding ADR rather than a quiet migration.

### 2026-08-09 — the renamed module/test, and the docstring finding repeating a third time

The 2026-08-08 amendment closed by giving `cache_compat.Cache` its docstring
back and pinning it with orm/tests/test_cache_compat_is_not_legacy.py
(deliberately not backticked: this path no longer exists). Both citations have
since moved: `e7822f78404` ("cache_compat.py was named for what it is not")
renamed the module to `orm/runtime/recordset_cache.py` and the test to
`orm/tests/test_recordset_cache_levels.py`. The `Cache` class keeps its
docstring at the new path; nothing here reopens the decision. Corrected in
place above.

The pattern that amendment named — "every deliverable of this record that was
a docstring has been deleted, and only the ones with tests survived" — has now
recurred for the *other* half, a third time and on a shorter cycle than the
first two. Step 1's replacement, "the class-level comment in
`orm/components/core.py`... carries the rest," was true when the 2026-08-08
amendment was written: the comment (added `6aef36aa534`, 2026-06-27) had
already been stripped once by `951226eb3fe` ("strip all Python and JavaScript
comments", 2026-07-25), then *restored* by `77decb3ab4b` (2026-08-07, the same
day's fact-check pass that produced this ADR's own 2026-08-07 amendments) —
so the claim was accurate at the moment it was made. It stopped being true two
days later: `d17ed6ff736` (2026-08-09, "strip prose comments from odoo/odoo per
eff67f80316, same sweep as the docstring pass") removed it again.
`orm/components/core.py` carries zero comments or docstrings at HEAD. The
doc-level half survives — `doc/architecture/module.md` and
`doc/architecture/runtime.md` still call `OrmCore` "the curated facade" — so
the decision is not undocumented, only the code-level comment this record
specifically named as its step-1 deliverable is gone again, on its third
add/strip cycle, all three strips being instances of the same class of
repo-wide comment/docstring sweep. Not corrected in place: a docstring
nominated as a deliverable and gated by nothing, decaying on a shortening
cycle, is the fact worth keeping, not a stale pointer.
