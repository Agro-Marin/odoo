# ADR-0010: Consolidate the internal cache/compute access surfaces around `env._core`

- **Status:** Accepted (steps 1–3 implemented; step 4 dropped on reassessment; step 5 deferred)
- **Date:** 2026-06-26

## Context

The two pure-engine objects of ADR-0002 — the per-transaction `FieldCache` and
`ComputeEngine` — are reachable through four handles. This is internal, distinct
from ADR-0008's addon-facing façade: the question is how *framework* code
reaches the cache and the compute engine.

| Handle | Level | Used by | Live? |
|---|---|---|---|
| `env._core` (`OrmCore`, `orm/components/core.py`) | id-level façade | framework ORM code (~29 call sites; `get_field_data` dominates) | **yes, growing** |
| `transaction.cache_store` / `transaction.compute_engine` | raw objects | `Transaction` internals (`clear`, building `core`) | public, but **~0 external readers** |
| `env.cache` (`cache_compat.Cache`) | recordset-level wrapper | addons: `contains`/`get_records`/`get_values`/`update`/`update_raw`/`set` (~16 sites across account/hr/sale/calendar) + `check()` in tests | legacy, still patched (`ad0f7064d72`) |
| `env`'s recompute/protect adapters (`is_protected`, `add_to_compute`, `protecting`, `records_to_compute`) | recordset-level | framework code holding recordsets | yes |

Two findings shape the decision.

**It is not a performance question.** `Field.__get__` inlines its own memo
(`env.__dict__["_field_cache_memo"][self]`) and reaches `env._core` only on a
per-`(field, env)` miss, which is then memoised. `OrmCore` is effectively never
on the per-record path. Any collapse is justified by clarity, not speed; an
earlier perf framing was refuted by measurement.

**The investment runs into `OrmCore`, not away from it.** `616425a2efc` routed
recompute-scheduler construction through `OrmCore.new_scheduler` so model code
stops reaching `core.engine`. `OrmCore` is documented as a *curated* surface,
not a complete mirror.

So the friction is narrower than "four surfaces":

- `OrmCore` is a curated subset (read, schedule, protect). Mutation
  (`set_value`, `invalidate_field`, `invalidate_all`) and lifecycle (`clear`,
  `prune_empty`) belong to `Transaction` and to `env.cache`. Defensible, but
  undocumented, so it reads as accidentally incomplete.
- ~25 hand-written pass-throughs can drift from `FieldCache`/`ComputeEngine`
  with nothing to catch it; `clear_cache` and `new_scheduler` already diverge
  from the docstring's "same name and contract" claim.
- `transaction.cache_store` / `compute_engine` are public attributes with no
  external readers — a third "right way" nobody needs.
- `env.cache` is a separate recordset-level wrapper still used by addons.

## Decision

Keep `OrmCore` as the internal id-level boundary; reduce the noise around it.

1. **Affirm `env._core` as the single id-level access point**, documented in
   `OrmCore`'s module docstring and `doc/architecture/ARCHITECTURE.md` as an
   intentionally curated subset: reads, dirty/patch tracking, scheduling and
   protection in; cache mutation and lifecycle out, by design.
2. **Privatise the raw handles.** `Transaction.cache_store` → `_cache_store`,
   `compute_engine` → `_compute_engine`. A few internal references and one test;
   removes a public surface at near-zero cost.
3. **Guard the façade against drift.** A unit test asserting each `OrmCore`
   pass-through delegates to the identically named `FieldCache`/`ComputeEngine`
   method, via a recording mock.
4. **Phase out `env.cache`** — *reassessed during implementation and **dropped**;
   see Implementation status.* ~~Migrate the ~16 addon call sites to `env._core`
   one method-family at a time, then delete the wrapper, keeping `check()` in a
   test-only home.~~
5. **Leave the recordset-level recompute/protect adapters on `env`.** Different
   abstraction level, correct where they are. Grouping them under
   `env.recompute` is cosmetic; out of scope.

## Alternatives considered

**Delete `OrmCore`; expose `env._cache` / `env._engine` directly.** Smallest
long-term surface, no pass-through maintenance, and both engines are already
cohesive APIs. Rejected: it contradicts the active investment in `OrmCore`
(`616425a2efc`), churns ~29 call sites for no functional gain, and trades a
curated id-level surface for coupling to the engines' full internal APIs. Worth
revisiting if the curation benefit fails to materialise.

**`OrmCore.__getattr__` delegating proxy.** Removes the maintenance, loses the
typed surface and the curation, and breaks if cache and engine ever share a
method name. Rejected.

**Status quo.** No bugs; the cost is ongoing ambiguity and silent-drift risk.
Steps 1–3 buy most of the clarity for little cost.

## Consequences

- One fewer public way to reach the engines. `env._core` is unambiguously the
  id-level handle, and its curation is documented intent.
- The façade grows a method only when production needs one, with a test
  guaranteeing the delegation — drift becomes a failing test, not a latent bug.
- No behavioural or performance change from steps 1–3.
- The smell reduces to `env._core` (id-level, framework) and `env.cache`
  (recordset-level), plus the recordset adapters at their own level.

## Migration plan

1. **Steps 1–3, one framework-only PR:** document the curated contract, rename
   the raw handles and fix internal references plus the one test reader, add the
   delegation drift-guard. Validate with `test_orm`, the `profiler` suite (which
   exercises `OrmCore` scheduling) and `base`.
2. **Step 4, phased per method-family**, each its own PR against the owning
   addons' suites.
3. **Optional later:** group `env`'s recompute/protect adapters.

## Risks & validation

- Privatising the raw handles could miss a reflective access. Grep confirms ~0
  non-test readers; `test_orm` and `base` cover the transaction lifecycle.
- The `env.cache` migration is the only addon-touching risk, hence phased.

## Enforcement

Steps 1–3 are guarded by the `OrmCore` delegation test and the standing
`test_orm` / `base` gates (ADR-0007). A `layer_check.py` contract forbidding
`_cache_store` / `_compute_engine` access outside `orm/runtime/transaction.py`
and `orm/components/` could follow if the naming convention proves insufficient.

## Implementation status

- **Steps 1–3: done.** `OrmCore` / `Environment._core` docstrings and
  `doc/architecture/ARCHITECTURE.md` document the curated boundary;
  `Transaction._cache_store` / `_compute_engine` are private, with the single
  external reader (an account test) moved to `env._core`;
  `TestOrmCoreDelegationDrift` in `orm/components/tests/test_core.py` asserts
  every pass-through delegates to its same-named method and that the table stays
  complete. Validated: component suite, `test_orm` (876), `profiler` (9).
- **Step 4: dropped.** `env.cache` is not redundant legacy — it is the
  **recordset-level** cache API, a context-aware wrapper over
  `field._get_cache` / `field._update_cache`, at a different level from the
  id-level `env._core`. The migration target was wrong: a mechanical rewrite
  would mishandle context-dependent fields (raw cache
  `{cache_key: {id: value}}`, not `{id: value}`), would couple addons to private
  field helpers, and some consumers live in `enterprise`/`agromarin`. `env.cache`
  is kept as the sanctioned recordset-level API. Genuinely shrinking it means
  eliminating addon cache-poking, a separate business-logic effort.
- **Step 5: not started** — optional, cosmetic.

## Amendments

A path named without backticks below no longer exists; backticking asserts it
does.

### 2026-08-07 — step 1's artefact was deleted, and step 2 was not true when it shipped

- **Step 1's deliverable no longer exists.** The ~30-line `OrmCore` module
  docstring was removed by the comment/docstring strip of `odoo/`
  (`eff67f80316`, 936 files, −49,443 lines). That strip kept an explicit
  retention list of machine-checked docstrings — `orm/__init__.py`, service/db.py
  (packagized away the next day by ADR-0014's `6920d626b7a`), all of `odoo/cli/`
  — and `orm/components/core.py` was not on it, because nothing read it. **A
  docstring nominated as an ADR deliverable and gated by nothing is not a
  deliverable.** `doc/architecture/ARCHITECTURE.md` still carries the
  curated-boundary statement.
- **Step 2 was incomplete on the day it landed.** Renaming
  `Transaction.cache_store` did not privatise the raw handles: `OrmCore`'s own
  slots were `cache` and `engine`, so `env._core.cache` *was*
  `transaction._cache_store`. Measured when found: 62 of 64 `_core.<attr>`
  accesses used a curated method, 2 reached the raw cache for `get_value`, which
  the façade did not expose. The slots are now `_cache` / `_engine`, `get_value`
  is on the façade, and `orm/tests/test_orm_core_facade_boundary.py` pins it.

Both were found by reading the tree, not the record — ADR-0008's point turned
inward: a documented guarantee no gate enforces decays into a claim.

### 2026-08-07 — the architecture front door moved to `doc/architecture/`

This record cited the front door at the path it held inside the core package
until 2026-08-07. Widening `doc_link_gate.py` to the set found 15 broken
references; the set is now one flat directory, `doc/architecture/`. Corrected in
place: the three pointers naming the page that carries the curated-boundary
statement.

### 2026-08-08 — this record's own prose still says "legacy", and the tree copied it

Step 4's reassessment kept `env.cache` as the sanctioned recordset-level API.
Three earlier lines disagree and remain, because the record is append-only: the
Context table (`legacy, still patched`), the bullet below it, and Consequences.
All predate the reassessment.

**The tree copied the wrong half.** `doc/architecture/module.md` read
"`env.cache` is the legacy recordset-level wrapper (ADR-0010)" until 2026-08-08
— sourced from Context, citing this record, contradicted by its own
Implementation status. A core audit reported it as an open question; the answer
was one section further down.

**The correction this record credits itself with was deleted.** Implementation
status says `env.cache`'s docstring was corrected to stop pointing callers at
`env._core`. `cache_compat.Cache` had no docstring at all by 2026-08-08 —
`eff67f80316` again. Twice in one record: **every deliverable of this record
that was a docstring has been deleted, and only the ones with tests survived.**

Closed without reopening the decision:

- `doc/architecture/module.md` states the relationship instead of the label, and
  says where the label came from.
- `cache_compat.Cache` carries the docstring again.
- `orm/tests/test_recordset_cache_levels.py` reads all three: that the class
  documents itself, that `doc/architecture/module.md` does not carry the label
  back, that nothing marks the class deprecated, and — the property the decision
  rests on — that `Cache` methods take recordsets while `OrmCore`'s take a field
  and a raw id. Convergence of those levels reopens the question, and would need
  a superseding record.

### 2026-08-09 — the renamed module/test, and the docstring finding a third time

`e7822f78404` ("cache_compat.py was named for what it is not") renamed the
module to `orm/runtime/recordset_cache.py` and the test to
`orm/tests/test_recordset_cache_levels.py`. The `Cache` class keeps its
docstring. Corrected in place above.

The pattern has recurred for the other half, on a shorter cycle. Step 1's
replacement — "the class-level comment in `orm/components/core.py` carries the
rest" — was true when written: the comment (`6aef36aa534`, 2026-06-27) had been
stripped by `951226eb3fe` (2026-07-25) and restored by `77decb3ab4b`
(2026-08-07). `d17ed6ff736` (2026-08-09) removed it again;
`orm/components/core.py` carries zero comments or docstrings at HEAD. The
doc-level half survives — `doc/architecture/module.md` and
`doc/architecture/runtime.md` call `OrmCore` "the curated facade" — so only the
code-level comment named as the step-1 deliverable is gone, on its third
add/strip cycle, all three from repo-wide sweeps. Not corrected in place: the
decay is the fact worth keeping.
