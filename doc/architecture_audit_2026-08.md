# Framework Core Architecture Audit — 2026-08

Scope: the framework core, `addons/odoo/odoo/` excluding the bundled addons —
**531 files / 126 kLOC** across 66 directories. Goal: best-in-class
architecture. This records **every directory explored**, what was found, and
which findings became proposals, fixes, or tests.

Baseline verified at start:
- `tooling/architecture/layer_check.py --check` → 8/8 contracts clean, 0 known
  violations, 6193 files scanned. The claims in `odoo/ARCHITECTURE.md` are real,
  not aspirational.
- Branch `19.0-marin` @ `3394fbe3405`.

Because the structural boundaries are already enforced and clean, this audit
deliberately targets **what the existing gates cannot see**: behavioural
coupling, invariants held only by convention, asymmetric APIs, and gaps where a
contract is documented but not pinned by a test.

## Legend

- 🔴 **Defect** — provable wrong behaviour.
- 🟠 **Structural risk** — works today, one edit away from breaking; no gate.
- 🟡 **Asymmetry / smell** — inconsistency that costs comprehension.
- 🟢 **Verified good** — explicitly checked, no action. Recorded so the next pass
  does not re-explore it.

---

## Exploration log

Every directory is covered. A **per-file** inventory — all 531 core files with
size, docstring summary and structural signals, across 66 directories — is the
companion document `architecture_inventory_2026-08.md`.

Scope note: `odoo/` is 1033 `.py` files / 335 kLOC, but 502 of those are the
bundled addons under `odoo/addons/`. The framework core audited here is
**531 files / 126 kLOC**.

| Dir | LOC | Files | Status | Outcome |
|---|---:|---:|---|---|
| `orm/models/` (mixins) | 8500 | 26 | ✅ | **F1** — hidden `self`-coupling; gate built |
| `orm/` (rest) | 37000 | 125 | ✅ | 🟢 layer seams verified sound (`_recordset`, `components/_protocols`, `OrmCore`) |
| `tools/` | 21751 | 78 | ✅ | **F2b**, **F5**; 18 files lack docstrings |
| `libs/` | 16752 | 137 | ✅ | 🟢 exemplary — 1 of 137 lacks a docstring, contract-free by gate |
| `db/` | 8251 | 36 | ✅ | **F3**; **F4** — claimed 🔴, disproved, downgraded to 🟡 |
| `http/` | 7994 | 34 | ✅ | **F3** — 11 modules undocumented incl. OpenAPI + typed routes |
| `tests/` | 7145 | 17 | ✅ | F2d 🟢 (bus dep is registry-guarded) |
| `service/` | 6880 | 20 | ✅ | F2c 🟢 (cron/job dep is deliberate, no overrides exist) |
| `cli/` | 3439 | 16 | ✅ | 🟡 14 of 16 files lack a module docstring |
| `upgrade_code/` | 3381 | 9 | ✅ | 🟢 dated migration scripts; `nodoc` is idiomatic here |
| `modules/` | 2670 | 8 | ✅ | 🟡 `loading.py` holds the 2nd/3rd longest functions in the core |
| `_monkeypatches/` | 777 | 16 | ✅ | 🟢 exemplary — README patch index, import-hook driven |
| `api/` `models/` `fields/` | 178 | 3 | ✅ | 🟢 verified: `__all__` exactly matches imports in all three (20/28/31) |
| `tooling/architecture/` | 3171 | 10 | ✅ | **F1, F2** (the gate gaps themselves) |

---

## Findings

### F1 🟠 The mixin decomposition's real coupling is invisible to every gate

`layer_check.py` reasons about **import** edges. `BaseModel` is composed from 18
`__slots__ = ()` mixins by multiple inheritance, and they collaborate through
`self` — which produces **no import edge at all**. So the single most intricate
coupling surface in the framework is entirely unmeasured.

Reconstructing it from the AST (`self.X` / `cls.X` resolved against the class
that defines `X`, restricted to genuine mixin classes) gives:

- **22 units, 85 inter-unit edges.**
- **One strongly-connected component of size 9**: `BaseModel`, `access`,
  `create`, `env`, `iteration`, `read`, `recompute`, `search`, `traversal`.
- **A second, independent 3-cycle**: `read_group/{mixin, format, fill}`.
- No accidental name collisions across mixins (only `__slots__`, as intended).
  The apparent dunder collisions (`__eq__`, `__getitem__`, …) are local helper
  classes — `ReversibleComparator` in `traversal.py`, `RecordCache` in
  `cache.py` — not MRO shadowing. Verified, not assumed.

> **Corrected after review.** The first pass reported *19 units, 75 edges* and a
> single residual 2-cycle. It was wrong. It treated the `read_group`
> **subpackage** as one unit, but `BaseModel.__mro__` contains four separate
> classes from it (`ReadGroupMixin`, `_ReadGroupSQLMixin`,
> `_ReadGroupFormatMixin`, `_ReadGroupFillMixin`). The collapse misattributed 14
> names and hid **10 edges and an entire 3-cycle**.
>
> It was caught by refusing to let the AST tool be its own oracle: importing the
> real class and diffing AST ownership against the runtime MRO. That check is now
> a permanent test (`TestAgreesWithTheRuntimeMro`), so the tool can no longer
> disagree with the class Python actually composes. *A subpackage is a
> directory; the MRO is the architecture.*

**What actually creates the cycle** (measured by removing one unit at a time):

| removed | largest remaining SCC |
|---|---:|
| **`BaseModel`** | **3** |
| `traversal` | 5 |
| `recompute` | 6 |
| `search` | 7 |
| any other single unit | 8–9 |

Removing `BaseModel` collapses the 9-cycle to **3**. The decomposition is
therefore *far* better than the raw SCC suggests: it is essentially a DAG plus

1. a genuine 2-cycle `read ↔ search`
   (`read → search`: `_search`, `_as_query`, `_field_to_sql`, `exists`;
   `search → read`: `_fetch_query`, `_determine_fields_to_fetch`, `fields_get`),
2. a 3-cycle inside `read_group` (see P5 — it is really two 2-cycles sharing a
   hub, and **one method** creates both back-edges), and
3. every mixin calling back into `BaseModel`.

And (2) is almost entirely **metadata, not behaviour**. The callback tally into
`base.py`: `_fields` (17), `_name` (16), `_table` (11), `pool` (8),
`_parent_name` (4), `_parent_store` (3), then a long tail of `_order`,
`_rec_name`, `_inherits`, `_abstract`, `_auto`, `_description`,
`_table_objects`, `_active_name`, `_check_company_auto`. Only ~5 of ~24 are
actual behaviour (`get_property_definition`, `_is_an_ordinary_table`,
`_onchange_methods`, `_clean_properties`, `_ondelete_methods`).

So `BaseModel` sits in the cycle because it is simultaneously the **composition
root** and the **model-metadata holder**. Those are two responsibilities.

### F2 🟠 The `odoo/` core → `odoo/addons/` direction is ungated

The eight contracts cover intra-core layering plus `addons → odoo.orm`
(`facade-boundary`). Nothing constrains the **reverse**: framework core taking a
dependency on a specific addon module. Today's inventory (AST-classified with
`layer_check`'s own TYPE_CHECKING semantics):

- **Legitimate — namespace/`__path__` addon discovery** (`import odoo.addons`,
  no addon *code*): `modules/module.py`, `tools/files.py`, `tools/translate.py`,
  `tools/assets/esbuild.py`, `cli/server.py`, `cli/upgrade_code.py`,
  `service/_watcher.py`. 🟢
- **F2c 🟢 `service/_threaded.py`, `service/_worker.py` → `ir_cron` / `ir_job`.**
  Checked for the obvious defect — calling `IrCron._process_jobs` on the
  *definition* class rather than through the registry would bypass any override.
  There are **no overrides** anywhere in `odoo`/`enterprise`/`agromarin`, and
  `_process_jobs` is a deliberate `@staticmethod` that opens its own cursor
  because it runs *before* a registry exists. Intentional, not a defect.
- **F2d 🟢 `tests/http.py` → `odoo.addons.bus`.** Guarded by
  `if "bus.bus" in self.env.registry:`. Correct.
- **F2a 🟡 `orm/models/mixins/unlink.py` → `ir_model_common.MODULE_UNINSTALL_FLAG`.**
  A plain string constant (`"_force_unlink"`) defined in an addon but consumed
  by the **ORM** at 3 sites, where it gates whether `@api.ondelete` methods run.
  Core behaviour keyed on an addon-owned constant; the dependency is inverted.
- **F2b 🟡 `tools/formatting.py` → `res_lang.format_number`** (2 deferred
  imports), plus `tools/locale_utils.py` and `tools/pdf/signature.py` importing
  `LangData` / `ResCompany` / `ResUsers` under `TYPE_CHECKING`. `format_number`'s
  own docstring says it is the *"pure, registry-free, DB-free"* counterpart of
  `ResLang.format` — i.e. it is already a pure function that does not belong in
  an addon model file.

### F3 🟠 `odoo/ARCHITECTURE.md`'s subsystem map has silently drifted from the tree

The *enforced* half of the architecture docs (the contract table) is exact. The
*descriptive* half — the subsystem map — is not gated by anything, and has
rotted. `doc_link_gate.py` checks that referenced `.md` files **exist**; nothing
checks that a described package still matches its directory.

| Package | Map lists | Actually contains | Undocumented |
|---|---:|---:|---|
| `db/` | 10 | 17 | `breaker`, `budget`, `lag`, `leaks`, `reaper`, `stats`, `utils` |
| `http/` | 8 | 19 | `core`, `controller`, `_serve`, `_params`, `_protocols`, `openapi`, `geoip`, `helpers`, `wrappers`, `exceptions`, `constants` |

This is not cosmetic. What is missing from `db/` is an entire **resilience
tier**, and each module is substantial and well-reasoned in its own docstring:

- `breaker.py` — circuit breaker with exponential backoff + single-prober claim.
- `lag.py` — replica apply-lag ceiling (`db_replica_max_lag`) that demotes
  read-only traffic to the primary.
- `budget.py` — process-wide `BoundedSemaphore` cap shared by both pools.
- `leaks.py` — who is holding checked-out connections, and since when.
- `reaper.py` — idle per-DSN pool reaping policy.
- `stats.py` — pool-level operational counters (distinct from `metrics.py`,
  which counts SQL per cursor).

And from `http/`: `openapi.py` generates an **OpenAPI 3.1 document** from the
routing map, and `_params.py` implements **annotation-driven typed routes**
(`@route(typed=True)`). Those are features, not helpers — a reader of
`odoo/ARCHITECTURE.md` would not know the framework has either.

### F4 🟡 `ReplicaLagGate.due_for_sample()` had no lock — downgraded from 🔴 after challenge

**My original claim was wrong and is retracted.** It is left here in full,
because how it failed is more useful than the finding was.

**What I claimed:** a 🔴 defect. `due_for_sample()` is a check-then-set with no
lock, on a gate hanging off the per-database `Registry` singleton that
`Registry.cursor(readonly=True)` hits from every worker thread. I "proved" it
with a test showing **8 of 8 concurrent readers claimed the sample slot**.

**Why that proof was invalid.** The test replaced `sample_interval` with an
object whose `__gt__` blocks on a barrier. A method call is an eval-breaker
checkpoint — one of the only places CPython honours a GIL drop request. So the
test *inserted the very race window it then reported finding*. With a real
float there is no such call. Disassembly settles it: between the `monotonic()`
CALL and the `STORE_ATTR`, the body contains **no call and no backward jump**,
so the read-and-stamp cannot be preempted on a GIL build.

**Three independent measurements, all negative:**

| experiment | result |
|---|---|
| Race the real pre-fix code from `git show HEAD:odoo/db/lag.py`, plain floats, 16 threads × 400 rounds, switch intervals 5 ms / 1e-4 / 1e-6 / 1e-9 | **0 duplicate claims**, max claims 1 |
| Real PostgreSQL 18.4, 16 concurrent `cursor(readonly=True)`, counting actual `LAG_SQL` round-trips | **1** round-trip, 0 errors, no deadlock |
| Same, with the **unfixed** gate as control | **1** round-trip — *identical* |

There is no observable difference between fixed and unfixed on this runtime.

**Additionally, the feature is off by default.** `db_replica_max_lag` defaults
to `0.0`, so `enabled` is false and the early return fires before the lock is
ever reached (measured: 36.7 ns unfixed vs 37.1 ns fixed on the disabled path).

**What survives the challenge:**

- 🟡 **The test was genuinely vacuous.** `test_only_one_of_many_racing_readers_samples`
  was `sum(1 for _ in range(50) if gate.due_for_sample())` — a sequential loop
  with no threads, passing identically with or without a lock. Real defect in
  the suite, unrelated to whether the lock is needed.
- 🟡 **The docstring made an unqualified exclusivity claim.** Its siblings
  qualify theirs: `stats.py` documents its unlocked counters as approximate
  under free-threading *with a measurement*; `reaper.py` states its caller must
  hold a lock. `lag.py` claimed the guarantee and explained nothing.
- ⚠️ **It would be a real data race on a free-threaded build**, where the
  bytecode-atomicity argument evaporates. But `db/` is **not** in the
  free-threading CI job's scope — `freethreading.yml` runs only
  `odoo/orm/components/tests` — so this is forward-looking, not current.

**Was `stats.py` the right precedent, or `breaker.py`?** Genuinely arguable, and
the answer decides whether the lock belongs. By *mechanism* they are the same
unlocked read/modify. By *consequence* they differ: `stats.py` loses counter
precision (harmless, documented); losing the lag claim costs duplicate DB
round-trips and, on the recovery path, duplicate replica cursors. `breaker.py`
— same package, same claim-a-slot semantics, same consequence class — locks.

**Decision: keep the lock**, on those grounds, not on the grounds I first gave.
It costs nothing on the default path and ~57 ns on an opt-in path that precedes
a DB round-trip. This is a judgement call and easy to reverse; flagged as such
rather than presented as a bug fix.

**What was actually changed:**

- `odoo/db/lag.py` — the lock, plus a docstring that now states the GIL
  measurement and names free-threading as the actual reason.
- `odoo/db/tests/test_lag.py` — the barrier test kept but **relabelled as fault
  injection**, opening with "This is fault injection, not a reproduction" and
  explaining why a test that merely starts threads would pass against the broken
  code. The vacuous test renamed to
  `test_repeated_sequential_calls_are_throttled` and documented as making no
  concurrency claim.

**Genuine gap this surfaced:** every existing `LAG_SQL` test asserts on the
*string* (`assertIn("pg_last_wal_receive_lsn() = ...", LAG_SQL)`). None had ever
run it against a server. It does work — PostgreSQL 18.4 returns `0.0` on a
primary, as the docstring claims — but that was unverified until this audit.


### F5 🟡 `tools/config.py::_build_cli` is a 1023-line method — but not the coupling problem it looks like

At 1023 lines it is **3× the next-longest** non-generated function in the core
(`modules/loading.py::load_modules`, 331) and 53% of its own 1929-line file,
which also has no module docstring.

The hypothesis worth testing was that option knowledge is smeared across the
class — that adding one option means touching six methods. **Measured, and it is
not true**: of 109 declared options, only **25** are referenced by name anywhere
outside `_build_cli`, 15 of them in `_postprocess_options`, which is legitimate
cross-option derivation. 84 options are purely declarative.

So this is a size and readability issue, not a coupling defect. Recorded with
the measurement so the next reader does not re-run the same hypothesis. The
useful framing: it is **declarative data expressed as imperative calls**, and
the honest remedy is a table-driven option spec, not decomposition into
`_build_cli_part_1..n`.

Secondary note: `config.py` is built on `optparse`, deprecated since Python 3.2,
on a Python-3.14-pinned runtime. Migrating is a real behavioural risk for modest
gain and is **not** recommended as part of this work — flagged only so the
choice is deliberate rather than inherited.

---

## What was delivered

Two things were implemented, not just proposed.

### 1. `odoo/db/lag.py` — the lock, honestly labelled

Not a bug fix; see the F4 retraction above for why. Kept as cheap insurance for
free-threading and for consistency with `breaker.py`, at zero cost on the
default path.

- `odoo/db/lag.py` — `threading.Lock` around the read-and-stamp, with a
  docstring that states the GIL measurement and names free-threading as the
  actual justification.
- `odoo/db/tests/test_lag.py` — the barrier test **relabelled as fault
  injection**, opening with "This is fault injection, not a reproduction"; the
  vacuous test renamed to `test_repeated_sequential_calls_are_throttled` and
  documented as making no concurrency claim.

### 2. Built the gate F1 says is missing

- `tooling/architecture/mixin_coupling_check.py` — reconstructs the mixin
  `self`-call graph and ratchets three numbers (`max_scc` 9, `edges` 85,
  `scc_without_base` 3) in the same exact-mode, drift-zero posture as
  `layer_check.py` and `tooling/ratchet/`. Supports `--check`, `--json`, and
  `--explain FROM TO` to list the members creating any single edge.
- `tooling/architecture/test_mixin_coupling_check.py` — 23 tests pinning the
  ways the checker could lie: counting local helper classes as mixins, missing
  `if TYPE_CHECKING:` declarations, mis-reporting cycles, and — added after the
  correction — **disagreeing with the runtime `BaseModel.__mro__`**.
- `.github/workflows/architecture.yml` — wired in beside its siblings; the
  existing `pytest tooling/architecture/` step already covers the self-test.

**Proven by mutation, on all three metrics.** Injecting `copy → write` moved
`edges` 85 → 86. Injecting `read → cache` pulled `cache` into the big cycle and
moved all three at once: `max_scc` 9 → 10, `edges` 85 → 86,
`scc_without_base` 3 → 4. Each time the gate exited **1**; each file was
restored byte-identically and it exited **0** again.

### Verification of the whole change set

| Gate | Result |
|---|---|
| Tier 1 (`pytest`) | **2315** passed, 645 subtests (2279 at start) |
| Tier 2 (`pytest odoo/orm/tests odoo/http/tests tests/service`) | 1421 passed |
| `pytest tooling/` | 412 passed |
| `layer_check.py --check` | **9/9** contracts, 0 new, 8 pinned, 6403 files |
| `mixin_coupling_check.py --check` | `max_scc` 9, `cyclic_edges` 31, `scc_without_base` 2 |
| `doc_link_gate.py` | 0 violations — it caught 4 broken refs in the first draft of *this* document |
| **`base` suite, real PostgreSQL 18.4** | **3144 tests, 0 failed, 4 errors — all 4 pre-existing** (below) |
| **`test_read_group`, real PostgreSQL** | **122 tests, 0 failed** |
| Real-DB replica-lag probe (disposable DB, dropped) | `LAG_SQL` valid, `0.0` on a primary; 16 concurrent readonly cursors, 0 errors, no deadlock |
| `ruff check tooling/ tests/` (must be zero) | clean |
| `ruff check odoo/` (ratchet floor 539) | **539** — unmoved |

**Pre-existing failure found, not caused by this work.** The `base` suite reports
4 errors, all in `TestSelfHandledArchMigration`
(`odoo/addons/base/tests/test_views.py`), all `AttributeError: 'ir.ui.view'
object has no attribute '_migrate_self_handled_arch'`. That method exists
**nowhere** in the tree — only the four calls in the test — so it is a test
written against an implementation that never landed, or removed with its tests
left behind. Neither `test_views.py` nor `ir_ui_view.py` is in this changeset.
Worth a separate fix.

**A grep that lied, caught only by the real database.** Before moving
`format_number` I searched for importers with `grep -v "res_lang.py"` to exclude
the source file — which also excluded every line of **`test_res_lang.py`**, whose
path contains that substring. The scan reported zero importers; there was one,
and the move broke database initialisation with `ImportError: cannot import name
'intersperse'`. Fixed by pointing the test at the new home. Static search said
the change was safe; only booting the server proved otherwise.
---

## Implementation status

| | status |
|---|---|
| **P5a** break the `read_group` 3-cycle | ✅ **done** — `cyclic_edges` 35 → 31, `scc_without_base` 3 → 2 |
| **P2** `core-does-not-depend-on-addons` | ✅ **done** — 9th contract, 2 inversions fixed, 2 pinned |
| **P3** `odoo/ARCHITECTURE.md` drift | ✅ **done** — `db/` resilience tier and `http/` features documented |
| **P1** extract `BaseModel` metadata | ✅ **done** — `max_scc` **9 → 2**, `cyclic_edges` **31 → 2** |
| **P4** docstring ratchet | not attempted (low value) |
| **P5b** `read ↔ search` | ✅ **done** — the mixin graph is now a **DAG** (`cyclic_edges` 0) |

### P5a — done

`_read_group_empty_value` moved from `read_group/mixin.py` to a new leaf
`read_group/_empty.py` (`_ReadGroupEmptyMixin`), which `fill` and `format` now
inherit. Both back-edges disappeared and the 3-cycle with them.

Verified: runtime MRO linearises as predicted (`ReadGroupMixin, SQL, Format,
Fill, Empty, _ModelStubs`); `_read_group_empty_value` resolves to the leaf; the
`enterprise/account_followup` override's `super()` chain still reaches it
(the leaf is in the live registry MRO); **122 `test_read_group` tests pass
against real PostgreSQL**; all four value branches verified live
(`__count`→0, m2o→empty recordset, `array_agg`→`[]`, char→`False`).

**It also exposed a flaw in the gate I had just built.** The refactor deleted a
cycle and the ratcheted `edges` count went *up* — 85 → 87 — because a new unit
brings its own edges. A metric that fires on a decomposition it should reward is
worse than no metric, so `edges` was replaced by **`cyclic_edges`** (edges whose
endpoints share a cycle), which fell 35 → 31. `edges` and `units` are still
reported, just not ratcheted. Pinned by `TestCyclicEdges`.

### P2 — done

Both inversions fixed rather than pinned:

- `MODULE_UNINSTALL_FLAG` → `orm/primitives.py`, exported through the
  `odoo.api` facade (addons may not import `odoo.orm.*`), re-exported from
  `ir_model_common` for the `ir_model*` / `ir_module` code that sets it.
- `format_number`, `intersperse`, `split`, `parse_grouping` →
  `libs/locale/number_format.py`, **moved verbatim** (an early draft rewrote
  `intersperse` from scratch; the original uses a regex plus a `split` helper
  with `0`/`-1` conventions, and the rewrite was wrong). Locale data arrives via
  a `LocaleConventions` **Protocol**, so `libs/` stays dependency-free and the
  addon's `LangData` satisfies it structurally without importing anything.

The contract needed one checker change: `Contract.allow_exact`, because prefix
matching cannot permit `import odoo.addons` (namespace `__path__` discovery)
while forbidding every `odoo.addons.<module>` under it.

Two entries are pinned, both intentional (`service/` → `ir_cron`/`ir_job`, which
run before a registry exists). The pre-existing "zero tolerated exceptions"
invariant test was **not deleted** — it was narrowed to assert the eight original
contracts stay clean and that every pinned entry belongs to the new contract and
carries a real rationale.

Drift protection: `test_core_source_covers_every_core_package` asserts the
explicit source list stays complete. It immediately earned its keep — it caught
`_monkeypatches` and `tests` missing. `_monkeypatches` was added;
`odoo.tests` is deliberately exempt (it is the test *framework*, and its
`odoo.addons.bus` use is already deferred and registry-guarded), recorded in
`CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT` so the omission is a decision rather
than an oversight.

### P1 — done: `BaseModel` is now only the composition root

**`max_scc` 9 → 2. `cyclic_edges` 31 → 2.** The only mixin cycle left in the
framework is `read ↔ search`.

**The original proposal was wrong and was not what got built.** It said to move
the metadata "into a Layer-2a descriptor that `BaseModel` and the mixins both
read". Measured first: `self._name` 528 call sites, `self._fields` 436,
`self._table` 236, `self.pool` 70 — **1270 across `odoo/addons`, `enterprise`
and `agromarin`**. Changing how those are *reached* is a breaking change to the
most-used surface in the framework, and it buys nothing the MRO does not already
give, because the coupling graph measures the **declaring unit**, not the access
syntax.

What was built instead keeps `self._fields` resolving exactly as before and
moves only the declarations:

| new leaf | what moved |
|---|---|
| `mixins/_metadata.py` | 28 metadata declarations (`_name`, `_table`, `_fields`, `pool`, `_order`, `_inherits`, …) plus the derived `_table_sql`, `_is_an_ordinary_table`, `_is_table_inheritance_root` |
| `mixins/_properties.py` | the 6-method `properties` feature (`get_property_definition`, `_clean_properties`, the two converters, …) |
| `mixins/_magic_fields.py` | `id` and `display_name` |

**Why it took all three.** `base.py` was the *articulation point*: the cycle was
`base.py → {create|env|traversal} → iteration → base.py`, and that last edge is
`IterationMixin.__int__` reading `self.id`. Moving the metadata alone got
`cyclic_edges` 31 → 25 and left `max_scc` at 9. Only when `id` moved too did
`base.py` leave the cycle.

**Three constraints found by reading the metaclass first, not by breaking things:**

- `_register = False` **must stay** in `BaseModel`'s own body.
  `MetaModel.__new__` reads it from the raw class-body `attrs` dict, not off the
  class, so `attrs.get("_register", True)` would return `True` and `BaseModel`
  would try to register itself → `ImportError: Invalid import of
  odoo.orm.models.base.BaseModel`. Same for `_magic_fields`, which is why
  `_register` is now a legitimate duplicate (recorded in the gate's
  `DUPLICATE_BY_DESIGN`, alongside `__slots__`).
- `_magic_fields` **must** carry `metaclass=MetaModel`. `Field.__set_name__`
  appends to `owner._field_definitions`, a list only `MetaModel.__new__`
  creates, and `registration.py` collects definitions with
  `if isinstance(cls, MetaModel)`. A plain holder would be skipped and **every
  model would silently lose `id`**.
- It must inherit `_ModelMetadataMixin`, not `_ModelStubs`: `__set_name__` reads
  `owner._name`, which the stub declares only under `TYPE_CHECKING`.

**One real bug, caught only by running the server.** `get_property_definition`
contains a *deferred* `from ..fields.properties import …`. One level deeper,
`..` resolves to `odoo.orm.models`, not `odoo.orm.fields` — so the import broke
at call time. Neither ruff nor import-time checks see a function-local import.
Fixed, then **every deferred import in `orm/models/` was resolved
programmatically** (5 checked, 0 broken) so no sibling was left behind.

**Regression evidence — a real A/B, not an assertion.** `test_orm` reported 3
failures after the refactor. Rather than assume, a **pristine `HEAD` worktree**
was built (detached, so the shared checkout other sessions are using was never
touched), given its own conf, data dir and DB, and run:

| | failures |
|---|---|
| refactored tree | `PropertiesCase.test_properties_field_many2many_basic`, `PropertiesCase.test_properties_web_read`, `TestUnityRead.test_properties` |
| **pristine `HEAD`** | **identical set** |

Zero regressions. Those 3 are pre-existing, in `orm/fields/properties.py` —
untouched by this work.

**An earlier 18-failure run was my own environment error**, recorded so it is not
re-derived: the DB was made with bare `createdb`, which bypasses the conf's
`db_template = tpl_p314o19marin` and so used `template1`'s `es_ES.UTF-8`
collation instead of `C`. Fifteen of the eighteen were string-ordering tests
(`TestSort.test_collation`, the domain-evaluator parity sweeps). Creating the DB
*through Odoo* dropped it to the 3 above. `CLAUDE.md` documents this trap; I hit
it anyway.

**Verified:** `base` 3144 tests / 0 failed / 4 pre-existing errors · `test_orm`
1049 tests, no new failures vs `HEAD` · `test_read_group` + `test_inherit` +
`test_inherits` 149 / 0 failed · a full `-i base` install from an empty DB.

### P5b — done: the mixin graph is a DAG

**`max_scc` 2 → 1. `cyclic_edges` 2 → 0.** There are no cycles left among the
`BaseModel` mixins at all.

The tangle was never really "read vs search". `read` needed `_search`,
`_as_query`, `_field_to_sql` and `exists` to turn a domain into rows; `search`
needed `_fetch_query`, `_determine_fields_to_fetch` and `fields_get` to
implement `search_fetch` / `search_read`. **Query construction was a third
concern with no home**, so the two mixins borrowed it from each other.

`mixins/_query.py` (`_QueryMixin`) gives it one. Membership was not a judgement
call — it is the transitive closure, inside `search.py`, of the four members
`read` reached for: `_search`, `_as_query`, `_field_to_sql`, `exists`,
`_check_qorder`, `_order_to_sql`, `_order_field_to_sql`, `_traverse_related_sql`.
That closure was verified up-front to need **nothing** from `read` or `search`
— only `_metadata`, `access`, `env`, `iteration` — which is what makes a leaf
possible. All eight moved **byte-identically** (checked by AST comparison
against `HEAD`).

`search` keeps what is actually *searching*: `search`, `search_count`,
`search_fetch`, `search_read`, `name_search`, the `_search_display_name*`
family, and the row locks. `search → read` survives as a plain DAG edge.

**The gate's meaning hardened.** With `cyclic_edges` at 0 it no longer bounds
the tangle, it forbids one. Mutation-proven: injecting a single
`_query → search` call rebuilt a 3-cycle and moved all three metrics
(`max_scc` 1 → 3, `cyclic_edges` 0 → 4, `scc_without_base` 1 → 3), exit 1;
restored byte-identically, exit 0.

**Verified:** Tier 1 2411 · Tier 2 1421 · tooling 508 · `base` 3144 tests /
0 failed / 4 pre-existing · `test_orm` + `test_read_group` + `test_inherit` +
`test_inherits` 1198 tests, only the 3 known pre-existing properties failures ·
**`test_performance` (which asserts exact query counts) clean** — the sharpest
check available on a query-path move · ruff ratchet unmoved at 539.

---

## Pre-existing defects this audit surfaced — all fixed

Each was confirmed against a pristine `HEAD` worktree before being touched, and
each fix was checked against **upstream `19.0`** rather than against its own
plausibility. That check changed the verdict twice.

**1. `TestSelfHandledArchMigration` — 4 errors. Half-landed feature; the missing
half is now implemented.**
`ir.ui.view._migrate_self_handled_arch()` did not exist. It was not an
abandoned direction: `@web/views/self_handled` ships, the view compiler reads
both spellings, JS tests cover it, and its docstring names this exact method as
the reason `SELF_HANDLED_ATTRS` still carries the Bootstrap entry. Only the
server half was missing, so it was written:

  * only `dropdown` and `modal` move — `data-bs-toggle` also drives collapse,
    tab, offcanvas and tooltip, which Bootstrap still owns;
  * `data-bs-target` follows a **modal** control only, and `data-bs-dismiss`
    only when it dismisses a modal, never an alert;
  * `qweb` arch is skipped — there the data-api is Bootstrap's own;
  * writes go through `arch_db` under `lang=None`. Writing `arch` under a
    non-English language would store the migration **as a translation** and
    leave the source arch untouched;
  * `no_save_prev=True` — a mechanical respelling is not an edit anyone wants
    to undo, and `arch_prev` is a single slot.

The rewrite rules live in `_rewrite_self_handled_nodes`, split out so they can
be exercised on a parsed tree with no view, database or search behind them.

**2. Properties read — 3 failures. A real fork regression, not a stale test.**
The first read was that `read(load=None)` returning bare ids looked *correct* —
`load` is documented as "avoid loading the display_name of m2o fields". Upstream
settles it: its `_read_format` calls
`field.convert_to_read_multi(values_list, self.browse(records))` for properties
and **deliberately never passes `use_display_name`**. The fork merged the
`properties` and `many2one` branches and began threading `load` into both.

That is not cosmetic. `web_read` (`addons/web/models/web_read.py:552`) reads
with `load=None` precisely because it resolves real relational fields itself
through the specification — but it cannot resolve a name buried inside a
properties blob, because the blob is opaque to that specification. The fork was
handing the web client bare ids where it expects `{id, name}`. Fixed in
`_read_format`, the layer that owns what `load` means; the three failures were
one defect.

**3. `test_check_field_access_rights_order` — 1 failure, and here the *test* was
the stale half.** Verified rather than assumed: upstream raises `AccessError`
from deep inside `_field_to_sql`; this fork added an earlier, explicit **drop**
in `_order_field_to_sql`. The stated reason checks out —
`res.users._has_field_access` really is record-sensitive (it grants
`SELF_READABLE_FIELDS` only when `self._origin == self.env.user`) and
`res.users._order` really is `"name, login"`, so raising fails closed on the
model-level empty recordset that `_order_to_sql` runs for, and users could no
longer sort or open their own preferences form. Dropping leaks nothing.

The test now pins the behaviour that actually matters. "Did not raise" would
pass just as well if the term were quietly *honoured* — the leak the drop
exists to prevent — so it asserts the column never reaches the SQL, in three
spellings, and that a readable term in the same clause still orders the query.
Both halves were mutation-proven: removing the drop kills the first, and
removing the deeper check too makes the term reach SQL as
`ORDER BY "…"."forbidden3"`, which the second catches.

**Verified:** `base` 3144 / 0 failed / **0 errors** (was 4) · `test_orm` +
`test_access_rights` 1080 / 0 failed (was 4) · Tier 1 2421 · Tier 2 1421 ·
tooling 518 · all gates green · ruff ratchet unmoved at 539.

---

## Proposals

**P1, P2, P3, P5a and P5b are all implemented** — see *Implementation status*
above for what was actually built, which differs from what some of these
originally proposed. They are kept below as the reasoning that led there. The
only one outstanding is **P4** (docstring ratchet, low value).

### P1 — Extract model metadata out of `BaseModel` (addresses F1) — **DONE**

Implemented; see *P1 — done* above for what was actually built and why the
proposal as originally written (a `_meta` descriptor) was discarded. Result:
`max_scc` 9 → 2, `cyclic_edges` 31 → 2.

### P2 — Add a `core-does-not-depend-on-addons` contract (addresses F2)

A ninth contract in `layer_check.py`: source `odoo` (excluding `odoo.addons`),
forbidden `odoo.addons.*`, with `odoo.addons` itself allowed (bare namespace
`__path__` discovery is legitimate and is 7 of the 15 runtime hits).

That leaves exactly two real entries, both cheaply fixable and both worth fixing
*before* turning the gate on so it starts at zero like its siblings:

- **F2a** — move `MODULE_UNINSTALL_FLAG = "_force_unlink"` from
  `addons/base/models/ir_model_common.py` into core (`orm/constants.py`), and
  have the addon import it from there. Pure motion of one string constant; the
  ORM stops depending on an addon to decide whether `@api.ondelete` runs.
- **F2b** — move `format_number` and `LangData` out of
  `addons/base/models/res_lang.py`. `format_number`'s own docstring already
  describes it as the *pure, registry-free, DB-free* counterpart of
  `ResLang.format`, which is a description of something that belongs in
  `libs/numbers/` or `libs/locale/`.

`service/ → ir_cron`/`ir_job` and `tests/http.py → bus` should be pinned as
`KNOWN_VIOLATIONS` with their rationale rather than "fixed" — both are
deliberate and correct (verified above).

### P3 — Gate the descriptive half of `odoo/ARCHITECTURE.md` (addresses F3)

`doc_link_gate.py` proves a referenced `.md` **exists**; nothing proves a
described package still **matches its directory**. Extend it (or add a sibling)
to assert every module in a mapped package appears in the map. Then repair the
current drift, which is the more urgent half:

- Add the `db/` **resilience tier** to the subsystem map — `breaker`, `lag`,
  `budget`, `leaks`, `reaper`, `stats`. A reader currently cannot learn from
  `odoo/ARCHITECTURE.md` that the framework has a circuit breaker or a replica-lag
  ceiling.
- Add `http/`'s `openapi` (OpenAPI 3.1 generation) and `_params`
  (annotation-driven typed routes). These are features, not helpers.

These modules are individually **well** documented — each has a docstring
explaining why it exists. The failure is purely that the top-level map never
aggregated them, which is exactly the failure mode a gate prevents.

### P4 — Even out module-docstring coverage (low priority, mechanical)

101 of 531 core files have no module docstring, and the distribution tracks
package quality: `libs/` 1/137 and `db/` 3/36 versus `cli/` 14/16, `tools/`
18/78, `http/` 13/34. Worth a ratchet in the existing `tooling/ratchet/` style
rather than a sweep — the `libs/` and `db/` docstrings are genuinely load-bearing
explanations, and a bulk fill would produce restatements of the filename.

### P5 — Break the two residual cycles

**P5a — the `read_group` 3-cycle: one method, and it is nearly free.**
Promoted from "low priority" once the corrected graph exposed it. The cycle
`mixin ↔ format` + `mixin ↔ fill` looks like three tangled modules, but
`--explain` shows both back-edges are the *same single method*:

```
read_group/mixin  -> read_group/format : _read_group_format_result,
                     _read_group_postprocess_aggregate, _read_group_postprocess_groupby
read_group/format -> read_group/mixin  : _read_group_empty_value      <-- only member
read_group/mixin  -> read_group/fill   : _read_group_fill_results, _read_group_fill_temporal
read_group/fill   -> read_group/mixin  : _read_group_empty_value      <-- only member
```

`_read_group_empty_value` (`read_group/mixin.py:446`) is a small helper — "what
the empty group is called" — called from `fill.py` ×3, `format.py` ×2 and
`mixin.py` ×1. Move it to a leaf (a new `_empty.py`, or wherever both can depend
downward) and **both** back-edges vanish, taking the whole 3-cycle with them.
`max_scc` is unaffected, `scc_without_base` should go 3 → 2. Small, isolated,
independently verifiable — the best first use of the new gate, and a good way to
rehearse the ratchet-lowering workflow before attempting P1.

**P5b — `read ↔ search`.** `read → search` via `_search`, `_as_query`,
`_field_to_sql`, `exists`; `search → read` via `_fetch_query`,
`_determine_fields_to_fetch`, `fields_get`. Query *construction* (`_as_query`,
`_field_to_sql`) is arguably a third concern both depend on. Genuinely
structural, unlike P5a; worth doing only after P1.

---

## Claims that did not survive challenge

Every finding above was re-attacked after the first draft. Two failed, and both
failures came from the same root cause: **letting a tool be its own oracle.**

| claim | verdict |
|---|---|
| F4 is a 🔴 defect; "8 of 8 readers claimed the slot" | **Retracted.** The test inserted the race window it reported. 0/1600 with real floats; identical round-trip count fixed vs unfixed against real PostgreSQL. Downgraded to 🟡. |
| F1: 19 units, 75 edges, one residual 2-cycle | **Corrected** to 22 / 85 / two cycles. The AST tool collapsed `read_group` into one unit; the runtime MRO has four classes there. |
| F5: 109 options, 25 named outside `_build_cli` | **Confirmed** against the live parser — all 109 declare `dest` explicitly, so the AST count was exact. |
| F3: `db/` 10→17 (7 undocumented), `http/` 8→19 (11) | **Confirmed** by direct enumeration. |
| F1: no cross-mixin name collisions | **Confirmed** at runtime — the only names defined by >1 composed class are compiler-generated dunders (`__doc__`, `__module__`, `__firstlineno__`). |
| F1: mixins are stateless `__slots__` fragments | **Confirmed** — no composed class lacks `__slots__`; `BaseModel` has no `__dict__`. |

Both corrections are now permanently guarded: `TestAgreesWithTheRuntimeMro`
diffs the AST model against `BaseModel.__mro__`, and the F4 test says in its
first line that it is fault injection rather than a reproduction.

The general lesson, which applies to the remaining proposals: an AST tool
agreeing with itself is not evidence, and a concurrency test that passes against
the broken code is worse than no test.

## Not pursued, and why

Recorded so the next pass does not re-derive them.

- **`IrCron._process_jobs` called on the definition class.** Looked like a
  registry-bypass bug that would silently drop overrides. There are none in
  `odoo`/`enterprise`/`agromarin`, and it is a deliberate `@staticmethod` that
  opens its own cursor because it runs before a registry exists. Correct.
- **Dunder collisions across mixins.** The first coupling scan reported `__eq__`,
  `__getitem__`, `__len__`, `__iter__` defined in two units each. They are local
  helper classes (`ReversibleComparator`, `RecordCache`), not MRO shadowing. The
  gate now excludes them by construction, and its self-test pins that.
- **`config.py` option scatter.** Hypothesis measured and disproved (F5).
- **`optparse` → `argparse` migration.** Real deprecation, poor risk/reward.
- **Unlocked counters in `db/stats.py`.** Deliberate and documented, with a
  measurement, and accepted as approximate on free-threaded builds. Not the same
  class of problem as F4, which claimed a guarantee it did not implement.
