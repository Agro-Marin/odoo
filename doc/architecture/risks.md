# Risks — where the implementation and the design disagree

> Referenced by [`ARCHITECTURE.md`](ARCHITECTURE.md). The views
> describe the architecture as it is meant to work. This page records the places
> where it **demonstrably does not**, or where the guarantee is thinner than the
> word suggests.

A blueprint that only describes the intent is an advertisement. Each entry below
names what is wrong, the evidence, what it would cost, and what would close it.
Entries are dated because a risk that is never re-checked becomes folklore.

**No entry here is speculative.** Anything that would need a "might" is not a
risk entry, it is a question — those live at the bottom of the view that owns
the subject, under *what this view does not cover*.

| # | Risk | Severity | Opened | Closed |
|---|---|---|---|---|
| R1 | `Registry._relation_reflections` has an undeclared lifetime | High | 2026-08-08 | **2026-08-09** |
| R2 | The layering is true of imports and false of the runtime graph | Medium | 2026-08-08 | — |
| R3 | Migration stage (`pre`/`post`) is unenforced and unrecoverable | High | 2026-08-08 | — |
| R4 | "Enforced" means structural only — 26 gates cannot see behaviour | High | 2026-08-08 | — |
| R5 | Two ADRs describe a subsystem the repository has never contained | Low | 2026-08-08 | — |
| R6 | Sibling-repo public-surface exposure is recorded, not paid down | Medium | 2026-08-08 | — |
| R7 | Every measured figure is single-process; contention is unmeasured | Medium | 2026-08-08 | — |

---

## R1 — `Registry._relation_reflections` has an undeclared lifetime — **CLOSED 2026-08-09**

**What.** The attribute was created inside `init_models`' `try:` and `del`-eted
in its `finally:`, so it existed *only* for the duration of that call. Layer 1
(`fields/relational/many2many.py`) mutated it, which worked solely because
`update_db` runs inside that window.

**Evidence.** `pool_surface_check.py`, where it was the first pinned violation;
written up in [`module.md`](module.md#coupling-the-import-graph-cannot-see).

**Cost if it broke.** Nothing declared the ordering, and nothing but an
`AttributeError` during module installation would have caught a violation — it
fails at install time, in the field, not in CI.

**How it was closed.** It was **four** attributes, not one: `_post_init_queue`,
`_foreign_keys`, `_relation_reflections` and `_is_install` shared the lifetime,
reached from five Layer-1 sites and the schema mixin, plus four `post_init`
calls from `addons/base`. All four are now fields of one `InitModelsPhase`
(`orm/runtime/_init_phase.py`) held as a single nullable `Registry._init_phase`
and read through the `init_phase` property, which raises a `RuntimeError`
naming the window and its purpose when the phase is closed. Layer 1's one
direct write became `pool.add_relation_reflection(...)`.

The strongest evidence that this was a defect and not a style was the
workaround already in the tree: `orm/runtime/_registry_stubs.py`, a class whose
entire body is `if TYPE_CHECKING:` declarations, inherited so mypy could see
attributes with no honest definition site — listing `_foreign_keys` and
`_is_install` beside genuinely permanent members and erasing the one
distinction that mattered. Both entries are gone from it.

Pinned by `odoo/orm/tests/test_init_models_phase.py`, which asserts the named
error on all three entry points outside the window.

**Note on the register.** This is the first risk to close, so it sets the
convention: the row keeps its number and gains a `Closed` date, and the section
is rewritten in the past tense with a *How it was closed* paragraph. Risks are
not deleted — a closed risk is the evidence that the register is read.

## R2 — The layering is true of imports and false of the runtime graph

**What.** The direction contracts are clean and always will be, because Layers 1
and 2 reach the runtime through `self.env` / `self.pool`, which produces no
import edge. Measured, **Layer 1 is the heavier consumer on both channels** — 4
unsanctioned `Environment` privates against Layer 2's 2, and 30 Registry sites
against 28.

**Evidence.** `env_surface_check.py`, `pool_surface_check.py`; see
[`module.md`](module.md#coupling-the-import-graph-cannot-see).

**Cost.** A reader who takes the layer diagram as the whole picture predicts the
wrong blast radius for a change to `Environment` or `Registry`. This is a
comprehension risk, not a correctness one — which is why it is Medium and why
the fix is documentation plus the two seam gates, both already in place.

**What would close it.** Nothing, strictly — the seam is the design. It is
recorded so the diagram is never read alone.

## R3 — Migration stage is unenforced and unrecoverable

**What.** `pre` is the only migration stage that can observe the old schema;
once the module graph converges, the columns have changed. A migration that
needs the previous representation and is filed as `post-` has nothing to read.

**Evidence.** `modules/migration.py::migrate_module`; threaded in
[`scenarios.md`](scenarios.md#scenario-b--upgrading-a-database-that-holds-data).

**Cost.** Silent data loss on upgrade of a populated database. Not caught by any
gate — all 26 are structural and DB-free — and not caught by either DB-free test
tier.

**What would close it.** A DB-backed upgrade test on a populated fixture, in the
integration lane. Nothing cheaper can see it.

## R4 — "Enforced" means structural only

**What.** The 26 boundary checkers read import graphs, call graphs, reached-member
sets and documents. None executes the framework. A change can satisfy all 26 and
both DB-free tiers and still be wrong.

**Evidence.** Recorded in [`gates.md`](gates.md#the-limits-of-enforced): renaming
`OrmCore`'s slots (`cache`/`engine` → `_cache`/`_engine`) broke two DB-backed
addon tests in 2026-08 while every gate and both tiers stayed green.

**Cost.** A green boundary job reads as "the framework works" when it means "the
structure holds". The integration lane is the only one that runs addon tests,
and it runs two suites.

**What would close it.** Broadening the integration lane is the only lever;
adding structural gates cannot reach this class of defect by construction.

## R5 — Two ADRs describe a subsystem the repository has never contained

**What.** ADR-0012 (attachment storage layers) and ADR-0013 (content placement)
sat at `Accepted` for a week while naming a subsystem that does not exist. Both
are now `Proposed`, which is the honest status.

**Evidence.** `doc/adr/README.md`, and each record's own Amendments section.
The existence check (`TestReferencedNamesExist`) is what caught it and now
exempts `Proposed`.

**Cost.** Low now that the status is correct — but the two records still
describe the intended shape of the `ir.attachment` dual-storage seam
([`data.md`](data.md#the-dual-storage-seam)), so a reader may take
them as current design.

**What would close it.** Build it, or supersede them.

## R6 — Sibling-repo public-surface exposure is recorded, not paid down

**What.** `web` publishes no API: everything under `static/src` is reachable as
`@web/<path>`. The pin records which specifiers each consumer scope reaches so
the surface can only shrink. On 2026-08-08 it was regenerated after 32 deep
imports in `agromarin` were rewritten to enter at their face, which removed the
deep entries and took it from 235 to 222; re-pinning against the real sibling
checkouts then took it to 219, and following `web`'s own module renames took it
to 222. Later the same day, removing three specifiers that resolved to no
module at all took it to **219 specifiers**. What remains is **recorded**, not
resolved.

Each of those moves was a separate commit, and one of them left this paragraph
stating 222 while the file said 219 — the pin and its prose are two copies of
one number, and only `test_the_public_surface_pin_size_is_measured` reads both.
Regenerating the pin without editing this line fails that gate; that is the
gate working.

**The 219 → 222 move was not new exposure, and part of it was not exposure at
all.** `web` dissolved `services/` in b6c0619c571, so `@web/services/user`
became `@web/core/user` and `browser`/`datetime`/`popover` moved with it;
`agromarin` followed in 0aa8c0f5 and the pin recorded the new names against the
scopes that reach them. But that same commit sent
`cloud_drive_s3/drive_action.js` to the *dissolved* name, and `--update`
recorded `@web/services/user` as surface — a specifier `web` has not published
since the dissolution, backing an import that could not load. It was repointed
at `@web/core/user` and the entry removed on 2026-08-08. The Trap below had
named this failure mode before it happened; what was missing was a gate that
read it.

**Now there is one.** `js_public_surface.py` resolves every measured specifier
against `web/static/src` — `a/b.js`, or `a/b/index.js` at a face — and fails on
one that matches neither, judged against the measurement rather than the pin so
a dead import is caught when it is written rather than after it is recorded.
It found two more the same day: `@web/legacy/js/core/dom` and
`@web/legacy/js/public/public_widget`, written by four
`design-themes/theme_common` files against the publicWidget system `web` has
not shipped since the native-ESM loader landed.

Those four were **deleted rather than ported**, because nothing loaded them.
`theme_common` never lists its own `data/ir_asset.xml` in the manifest — its
siblings `theme_avantgarde` and `theme_graphene` do list theirs — so the
records were never created; the three naming JS were `active=False` regardless;
and no other theme references their keys. Three unreachable `theme.ir.asset`
records went with the files, plus a fourth naming a JS file deleted long before.
`KNOWN_UNRESOLVED` is therefore empty, which is the state to keep it in.

A count that rises because the *names* moved is not the same as one that rises
because a consumer reached deeper — but this file cannot tell the two apart,
which is why the shape gate (`js_face_boundary.py`) was added alongside: it
refuses a specifier that steps over a face regardless of how the count moves.

**Evidence.** `tooling/architecture/public_surface_web.txt`;
`js_public_surface.py`.

**Cost.** Every pinned specifier is a rename `web` cannot perform unilaterally.

**Trap.** `--update` regenerates the pin against whatever the tree currently
imports, and it is only as honest as that tree. Two ways to get it wrong, both
hit on 2026-08-08:

- Run it *before* fixing face violations and it records the deep paths as
  legitimate exposure — that produced 245 specifiers rather than 222.
  **Fix the violations first, regenerate second.**
- Run it against **stale sibling checkouts** and it pins specifiers that resolve
  to nothing: `--check` compares the pin to the same tree that produced it, so a
  wrong pin and a stale checkout agree with each other, and the drift surfaces
  only where the siblings are current — in someone else's workspace. **Confirm
  every sibling is up to date before regenerating**, and treat a pinned
  specifier that resolves to no file as evidence the harvest was wrong rather
  than as surface to preserve.

  This half is now enforced rather than advised: `unresolved()` resolves each
  measured specifier against `web/static/src` and fails on one backed by no
  module, so a dead import can no longer be laundered into the pin by a
  regeneration. It cannot make a *stale* checkout current — a specifier the
  siblings no longer import still needs the sibling to be up to date — but it
  does catch the class of wrong pin that staleness produces.

The 245, the 222 and the 219 are each of their day; the pin's size today is the
one above.

## R7 — Every measured figure is single-process

**What.** All of [`qualities.md`](qualities.md) was measured with `workers = 0`,
threaded, on loopback, with no concurrent writers.

**Cost.** The forces the numbers are meant to defend — *correctness under
contention*, *horizontal scale* — are precisely the ones no figure covers.
`retrying()`'s re-run rate and cost under real concurrency are unknown, and the
cross-process signalling path is exercised by none of the measurements.

**What would close it.** A `workers > 0` measurement with a concurrent writer,
recording retry rate, p99 under contention, and the signalling round-trip.

---

## Adding an entry

Give it a number, a date, the evidence that makes it checkable, the cost if it
bites, and what would close it. An entry with no closing condition is a
complaint. When one is closed, say so with the date and leave it in place —
this page is a record, not a queue.
