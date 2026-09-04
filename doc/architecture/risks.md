# Risks — where the implementation and the design disagree

> Referenced by [`ARCHITECTURE.md`](ARCHITECTURE.md). The views describe the
> architecture as it is meant to work. This page records where it
> **demonstrably does not**, or where the guarantee is thinner than the word
> suggests.

Each entry names what is wrong, the evidence, what it would cost, and what would
close it. Entries are dated because a risk that is never re-checked becomes
folklore.

**No entry here is speculative.** Anything needing a "might" is not a risk, it is
a question — those live at the bottom of the view that owns the subject, under
*what this view does not cover*.

| # | Risk | Severity | Opened | Closed |
|---|---|---|---|---|
| R1 | `Registry._relation_reflections` has an undeclared lifetime | High | 2026-08-08 | **2026-08-09** |
| R2 | The layering is true of imports and false of the runtime graph | Medium | 2026-08-08 | — |
| R3 | Migration stage (`pre`/`post`) is unenforced and unrecoverable | High | 2026-08-08 | — |
| R4 | "Enforced" means structural only — 71 gates cannot see behaviour | High | 2026-08-08 | — |
| R5 | Two ADRs describe a subsystem the repository has never contained | Low | 2026-08-08 | **2026-08-14** |
| R6 | Sibling-repo public-surface exposure is recorded, not paid down | Medium | 2026-08-08 | — |
| R7 | Every measured figure is single-process | Medium | 2026-08-08 | **2026-08-28** |
| R8 | The integration lane is headless, so the tours it selects skip as passes | High | 2026-09-02 | — |
| R9 | A recursive stored compute has a shape no DB-free tier can pin | Medium | 2026-09-02 | — |
| R10 | Most gate modules state their reason nowhere | Medium | 2026-09-02 | — |

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
and read through the `init_phase` property, which raises a `RuntimeError` naming
the window and its purpose when the phase is closed. Layer 1's one direct write
became `pool.add_relation_reflection(...)`.

The strongest evidence that this was a defect and not a style was the workaround
already in the tree: `orm/runtime/_registry_stubs.py`, a class whose entire body
is `if TYPE_CHECKING:` declarations, inherited so mypy could see attributes with
no honest definition site — listing `_foreign_keys` and `_is_install` beside
genuinely permanent members. Both entries are gone from it.

Pinned by `odoo/orm/tests/test_init_models_phase.py`, which asserts the named
error on all three entry points outside the window.

**Convention this sets.** A closed risk keeps its number, gains a `Closed` date,
and is rewritten in the past tense with a *How it was closed* paragraph. Risks
are not deleted — a closed risk is the evidence that the register is read.

## R2 — The layering is true of imports and false of the runtime graph

**What.** The direction contracts are clean and always will be, because Layers 1
and 2 reach the runtime through `self.env` / `self.pool`, which produces no
import edge. Measured, **Layer 1 is the heavier consumer on the `Environment`
channel and the two are within two accesses of each other on the `Registry`
one** — 4 unsanctioned `Environment` privates against Layer 2's 2, and 28
Registry sites against 30.

**Evidence.** `env_surface_check.py`, `pool_surface_check.py`; see
[`module.md`](module.md#coupling-the-import-graph-cannot-see).

**Cost.** A reader who takes the layer diagram as the whole picture predicts the
wrong blast radius for a change to `Environment` or `Registry`. A comprehension
risk, not a correctness one — which is why it is Medium and why the fix is
documentation plus the two seam gates, both already in place.

**What would close it.** Nothing, strictly — the seam is the design. It is
recorded so the diagram is never read alone.

**Widened 2026-08-09, and that widening closed 2026-09-01: it was not only
Layers 1 and 2.** Until 2026-09-01 `odoo/tools/files.py` reached
`env.transaction.file_open_tmp_paths` — the `file_open()` sandbox allowlist — at
4 sites. `tools/` is the one package whose contract names the runtime explicitly
(`tools-does-not-reach-the-orm-runtime`), and that contract was clean
throughout, because the reach arrived through `env` and produced no import edge.
Neither seam gate reported it either: `_orm_layer_scope.py` scopes both
`env_surface_check` and `pool_surface_check` to `orm/*`, so a reach from
`tools/` was outside what either measured.

The gap was therefore wider than the two layers it was opened against: it
covered every package holding an `Environment`, and the one place it was
*contractually* forbidden was the one place nothing looked.

*How the widening was closed.* By taking the second of the two steps recorded
here and skipping the first. The allowlist never needed the transaction; it
needed a lifetime — the `with file_open_temporary_directory()` block, on the
thread that opened it — and a `contextvars.ContextVar` in `tools/files.py`
gives it exactly that. `Transaction` no longer carries `file_open_tmp_paths`,
`files.py` reaches the transaction at 0 sites, and `module_view.py` pins that
zero so the reach cannot return unread. The `tools/` scope for
`_orm_layer_scope.py` was not added: with nothing in `tools/` holding runtime
state it would measure a constant zero, which is the doc-gate pin under another
name. R2 itself stays open — the seam is still the design.

## R3 — Migration stage is unenforced and unrecoverable

**What.** `pre` is the only migration stage that can observe the old schema;
once the module graph converges, the columns have changed. A migration that
needs the previous representation and is filed as `post-` has nothing to read.

**Evidence.** `modules/migration.py::migrate_module`; threaded in
[`scenarios.md`](scenarios.md#scenario-b--upgrading-a-database-that-holds-data).

**Cost.** Silent data loss on upgrade of a populated database. Not caught by any
gate — all 71 are structural and DB-free — and not caught by either DB-free test
tier.

**Narrowed 2026-08-09: the syntactic half is caught, the semantic half is the
risk.** The two were being treated as one. Nothing can know that a script
reading the old schema was filed as `post-` — that is the entry. But
`_get_migration_files` selects on `name.startswith(f"{stage}-")`, so a script
named `pre_01.py` or `Pre-01.py` (the match is case-sensitive) matches no stage
at all: globbed, collected, then dropped by every stage without a word. On an
upgrade of a populated database that is a migration nobody notices did not
happen, and it needed no schema knowledge to detect.
`modules/migration.py::_warn_unstaged_scripts` now logs one, as a warning rather
than an error, because an addon may legitimately keep a helper module beside its
scripts. Measured across this repository's two addon trees — the scope CI
reproduces, a workspace reading being whatever checkouts happened to be on
disk: **275** scripts in `migrations/` and **5** in `upgrades/`, all correctly
prefixed, **0** dropped.

A risk stated at the level of its hardest half hides the half that is cheap to
close.

**Narrowed again 2026-08-28: the guarantee is under test; the filing is not.**
`tests/loading/test_migration_schema_visibility.py` installs a probe module at
1.0, rewrites it to 1.1 with a new field and one script per stage, upgrades, and
asks each script — through `information_schema`, since the registry's field list
is what the module *declares* rather than what the table *has* — what it could
see when it ran. `pre` sees no column; `post` sees it. That is the first test
anywhere of the ordering this entry rests on, and no fixture tree can do it:
`test_migration_ordering` covers which scripts run and in what order, against
filenames, which is a different claim.

Three mutations were checked against it, and the third is this entry's own
narrowed half reproduced in a database: probing a column that already exists
fails the `pre` assertion; a version directory that matches no stage, and
scripts whose stage prefix is spelled with an underscore rather than the hyphen
`_get_migration_files` selects on, each fail the guard that refuses to let the
suite pass having run nothing.

(Both spellings were written into this paragraph as backticked filenames first,
and `test_every_backticked_python_file_exists` refused them — a name in
backticks on these pages asserts the file exists. The exemption list is for the
two hypothetical names above, and it stays that size by rewording rather than
growing.)

**What is left, and it is the original entry.** An author can still file a
script that reads the old schema as `post-`, and nothing will notice: the
guarantee is now tested, the *use* of it is not, and no test of the framework
can distinguish a `post-` script that wanted the new schema from one that
needed the old. What would close it is a review rule, not a gate.

**What would close it.** Nothing mechanical. The stage semantics are pinned; the
remaining half is a property of each migration an addon author writes, which is
why this entry stays open at High rather than closing on the test above.

## R4 — "Enforced" means structural only

**What.** The 71 boundary checkers read import graphs, call graphs,
reached-member sets and documents. None executes the framework. A change can
satisfy all 71 and both DB-free tiers and still be wrong.

**Evidence.** Recorded in [`gates.md`](gates.md#the-limits-of-enforced): renaming
`OrmCore`'s slots (`cache`/`engine` → `_cache`/`_engine`) broke two DB-backed
addon tests in 2026-08 while every gate and both tiers stayed green.

**Cost.** A green boundary job reads as "the framework works" when it means "the
structure holds". Two lanes execute addon tests: the integration lane is the only
one that runs addon tests in Python, and it runs twenty-nine suites; the JS lane
(`js_tests.yml`, added 2026-09-01) runs the HOOT suites under both presets.

**Widened 2026-09-02: the Python lane is headless as well as narrow.** Nearly
every one of its suites passes `--no-http` — R8 carries the figure and the
mechanism — so what "runs addon tests" executes is the database half of each
suite and not its browser half. An `HttpCase` class skips itself at `setUpClass`
and is reported as skipped, never as a failure, so the lane's green covers the
tours and the served-controller tests of a suite it names exactly as well as the
boundary job covers behaviour: not at all. The sentence above therefore reads
"runs the addon tests that need no server" for all but the two suites R8 names,
and the defect class this entry opened on — green everywhere, wrong at runtime —
has a second instance in R9, where the tier that stayed green cannot hold the
state the defect needs.

**What would close it.** Broadening the integration lane is the only lever —
more suites, and a server under the ones already there (R8) — because adding
structural gates cannot reach this class of defect by construction.

## R5 — Two ADRs describe a subsystem the repository has never contained — **CLOSED 2026-08-14**

**What.** The attachment-storage-layers and content-placement records of the
decision register (itself since deleted) sat at `Accepted` for a week while naming a subsystem that does not exist, then
at `Proposed` for a fortnight while nobody built it.

**Evidence.** The decision register, and each record's own Amendments section. The
existence check (`TestReferencedNamesExist`) caught the false `Accepted` and
exempts the unbuilt statuses.

**How it closed.** The work was confirmed abandoned and both records are
`Withdrawn`, each with an amendment saying so — the third answer to "build it or
supersede it", added to the status vocabulary for exactly this case. The seam
they described is now stated directly in
[`data.md`](data.md#the-dual-storage-seam), so no reader has to open a withdrawn
record to learn what `ir.attachment`'s dual storage costs.

## R6 — Sibling-repo public-surface exposure is recorded, not paid down

**What.** `web` publishes no API: everything under `static/src` is reachable as
`@web/<path>`. The pin records which specifiers each consumer scope reaches, so
the surface can only shrink. It stands at **230 specifiers**
(`tooling/architecture/public_surface_web.txt`). What remains is *recorded*, not
resolved.

**Cost.** Every pinned specifier is a rename `web` cannot perform unilaterally.

**How it got there**, since the path explains what the number does and does not
mean:

| Move | Size | What it was |
|---|---:|---|
| baseline | 235 | before 32 deep imports in `agromarin` were rewritten to enter at their face |
| after the rewrite | 222 | deep entries removed |
| re-pinned against real sibling checkouts | 219 | |
| following `web`'s own module renames | 222 | `web` dissolved `services/` in b6c0619c571, so `@web/services/user` became `@web/core/user` and `browser`/`datetime`/`popover` moved with it; `agromarin` followed in 0aa8c0f5 |
| removing specifiers backed by no module | 219 | |
| `date_range` entered at the `@web/core/tree` face | **218** | `in_range_providers` was reached directly by the only consumer outside `web`; the face republishes it, so the file stops being surface |
| `fields/field_options` published | **219** | the shared `supportedOptions` entries, reached by `html_editor` and `analytic`; one option descriptor had been written out twelve times across ten files, so this is a specifier bought deliberately to delete duplication |
| the search bar split, and one selector newly reached | **221** | `adfb8afce15` gave `purchase_stock` and `product` real accessors instead of reaching around the search model, and split `search_bar` into `search_bar` and `search_bar_toggler` — one pinned specifier becoming two is +1 with no new exposure — while `components/record_selectors/avatar_models` is a genuinely new one specifier |
| the enterprise web client folded into `web` | **229** | `c0481e4b06e` moved the home menu, the app switcher and the Studio upsell into `web` and `caa80b58e1b` deleted the module, so `home_menu` and `promote_studio`'s three specifiers are now reached from `enterprise` rather than shipped there — four entries the pin had never needed to carry |
| the flow editor published for `automation` | **230** | `automation`'s workflow canvas is the first consumer of `@web/core/flow_editor/flow_editor`, the node-graph editor backported from the enterprise call-flow builder; one specifier, entered at the component's own module rather than at the geometry and store beneath it |
| **today** | **230 specifiers** | the rows above are the moves that were written down, not the whole path; this row is the pin's size on disk, and saying `specifiers` is what puts it under `test_the_public_surface_pin_size_is_measured` rather than beside it. A table of moves that stops short of the figure the prose states is two records of one number, which is the thing this register says not to keep |

**A scope is not a specifier.** Recording that `agromarin`'s `geoengine` also
enters at `@web/views/widgets` added a third scope tag to a line already pinned
for `odoo` and `enterprise`, and moved this figure by nothing. The number counts
what `web` cannot rename; a second consumer of an already-published specifier
constrains `web` no further.

**The 219 → 222 move was not new exposure, and part of it was not exposure at
all.** The same commit that followed the renames sent
`cloud_drive_s3/drive_action.js` to the *dissolved* name, and `--update`
recorded `@web/services/user` as surface — a specifier `web` has not published
since the dissolution, backing an import that could not load.

**A gate now reads the pin.** `js_public_surface.py` resolves every measured
specifier against `web/static/src` — `a/b.js`, or `a/b/index.js` at a face — and
fails on one matching neither, judged against the *measurement* rather than the
pin, so a dead import is caught when it is written rather than after it is
recorded. It found two more the same day, `@web/legacy/js/core/dom` and
`@web/legacy/js/public/public_widget`, in four `design-themes/theme_common`
files written against the publicWidget system `web` has not shipped since the
native-ESM loader landed. Those four were **deleted rather than ported**:
`theme_common` never lists its own `data/ir_asset.xml` in the manifest (its
siblings `theme_avantgarde` and `theme_graphene` do list theirs), so the records
were never created; the three naming JS were `active=False` regardless; and no
other theme references their keys. Four unreachable `theme.ir.asset` records
went with the files. `KNOWN_UNRESOLVED` is therefore empty, which is the state
to keep it in.

A count that rises because the *names* moved is not the same as one that rises
because a consumer reached deeper, and this file cannot tell the two apart —
which is why the shape gate (`js_face_boundary.py`) was added alongside: it
refuses a specifier that steps over a face regardless of how the count moves.

**Evidence.** `tooling/architecture/public_surface_web.txt`;
`js_public_surface.py`. The pin's size and this page are two copies of one
number, and `test_the_public_surface_pin_size_is_measured` reads both:
regenerating the pin without editing this entry fails that gate.

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
  than as surface to preserve. `unresolved()` now enforces this half, but it
  cannot make a stale checkout current.

## R7 — Every measured figure is single-process — **CLOSED 2026-08-28**

**What.** Every figure on [`qualities.md`](qualities.md) was measured with
`workers = 0`, threaded, on loopback, with no concurrent writers. Scenarios 5
and 6 are now the exceptions and say so; the first four still are not, and are
not meant to be — the page keeps them as the single-process baseline the other
two are read against.

**Cost.** The forces the numbers are meant to defend — *correctness under
contention*, *horizontal scale* — were precisely the ones no figure covered.
`retrying()`'s re-run rate and cost under real concurrency were unknown, and the
cross-process signalling path was exercised by none of the measurements.

**Half closed 2026-08-28: contention.** [Scenario 5](qualities.md#scenario-5--contention-and-retry) runs
`workers = 4` under prefork with sixteen concurrent writers, against a control
at the same concurrency on different rows. Same-row contention costs ~3× the
throughput, ~2.5× the p50 and 5–10× the p99, and turns a lane with no failures
into one losing **0.5 % of requests to an exhausted retry budget**.

The result worth carrying into design is not the ratio: **the retry ladder
barely converges.** Two thirds to three quarters of the requests that need one
retry need another, at every depth, so 22 % of everything that ever retried
failed outright. `retrying()` spreads a *burst* apart; under a load that never
stops offering, a retry lands back into the contention it left and the mechanism
settles at a fixed loss rate rather than at zero. A retry budget is not a queue,
and no budget converts sustained same-row write contention into success.

**Closed 2026-08-28 by the second half.**
[Scenario 6](qualities.md#scenario-6--cross-process-invalidation) measures the
signalling round trip: a cache clear reaches every other worker in **1 ms at
p50, 3 ms at p95**, complete fan-out, when the workers are busy — and reaches
nobody when they are idle, which is the mechanism working rather than failing.
`check_signaling()` runs in `_acquire_registry_cursor` on the cursor the request
was already taking, **before dispatch**, so it is a poll at request start and
not a push: a worker serving nothing cannot serve a stale cache, and the first
request it takes clears the cache before the handler sees it. The whole check is
one `SELECT` of eight scalar subqueries, **1.08 ms**, on a cursor already open.

Both halves of this entry are now measured, so it closes. What it leaves behind
is stated on the page rather than here: where between total conflict and none
the retry ladder begins to converge, and the replica case — signalling read
through a cursor that lands on a replica merely *behind* reads as "nothing has
changed".

## R8 — The integration lane is headless, so the tours it selects skip as passes

**What.** Every `HttpCase` — a tour, and any test that drives a browser or an
HTTP client against the server — needs a running HTTP server, and `--no-http`
starts none. Such a class skips itself at `setUpClass`, which never reaches
`startTest`, so it adds nothing to the test count and the log records a skip
where the suite's author wrote a test. **22** of the **29** suites the
integration lane runs pass `--no-http`; `test_http` and `rpc` are the two that do
not, and each carries a count floor set *above* what a headless run of the same
suite reports, so that a re-added flag fails the lane instead of passing it. The
other browser lane does not reach a tour either: `js_tests.yml` (`15fb00aab7a`)
runs the HOOT unit suites under both presets with a passed-count floor per pass,
and a HOOT suite mounts components against a mock server — it is the browser
without the framework, where a tour is the framework driven through the browser.
Between the two lanes, a tour runs nowhere.

**Evidence.** `hr_holidays`'s `time_off_request_calendar_view` tour fails at its
last step on a pristine checkout — the click that should open the new-leave
dialog opens nothing — and no headless run can see it: the class is reported as
skipped, never as a pass, which is how it stayed unnoticed. The `rpc` suite's own
floor comment records the shape from the other side: a headless run reports
fewer tests than a served one, and every test in the difference is an `HttpCase`
skipped as a success. Since `c430b51ef26` the exit code does catch one edge of
this — a post-install phase that *prepared* tests and *started none* fails the
run, so a lane whose whole selected suite is `HttpCase` goes red — but a mixed
suite that skips its browser half and runs its database half is exactly the
shape the exit code still calls a pass.

**Cost.** A tour regression lands green, and stays green until somebody runs the
suite by hand with a server. Every tour in the lane's suites is coverage the lane
claims and does not have; every `--no-http` flag is a decision that the
tour classes of that suite are deferred, taken once and then re-read as a pass
on every push.

**What would close it.** Chrome on the runner and the flag dropped suite by
suite, each drop paired with its count floor raised to the served figure — the
`rpc` suite is the template, floor comment included. The floor is the
load-bearing half: a flag dropped without it lets the skip come back unread, and
a floor set from the headless count ratifies the skip. The figure above is
measured from the workflow, so each suite that drops the flag moves it, and the
entry closes when it reads zero.

## R9 — A recursive stored compute has a shape no DB-free tier can pin

**What.** `e8ff3f09c9e` fixed `_recompute_singly`
(`odoo/orm/fields/_field_compute.py`): a single-record read of a `store=True,
recursive=True` field widened into the field's whole pending set on every read,
including the nested read a compute issues for its parent's value of the same
field. In that nested frame the ancestor whose compute is in progress is
protected and has no cache entry, so a descendant computed there fell through to
the stored column, read the value from before the write that scheduled the
recompute, stored it, and was marked done — and the protected assignment path
never calls `modified()`, so nothing marked it again. The stale rows are the
descendants of whichever record was read first. The fix widens the batch only
when no record of the field is protected. What stays open is the *shape*, not
the defect: a stored recursive compute on a model whose `_order` is not
tree-ordered, where a fetch does not flush the field before the nested read can
happen.

**Evidence.** `test_orm`'s
`test_12_recursive_stored_value_survives_a_middle_first_read` pins the fix, and
it is database-backed on purpose: `InMemoryBackend.search`
(`odoo/orm/runtime/backend.py`) flushes everything unconditionally where
PostgreSQL flushes only the fields the query reaches, so the deferred pending set
the defect needs never exists in Tier 2. The defect was live for as long as the
shape was, and both DB-free tiers were green throughout — R4's pattern with a
worked instance, and the reason it is recorded as a shape rather than closed as a
bug. Shipped models carry the shape in this repository and in `enterprise`;
`account.analytic.plan` and `stock.package` do here. `hr.department` and
`product.category` carry the same fields and cannot reproduce it, because a
tree-ordered `_order` makes the fetch flush the field first — a test written
against either is green on both sides of the fix, which is the trap for whoever
adds the next one. `res.partner.commercial_partner_id` has the identical shape
with no materialised path, and record rules anchor `domain_force` on it.

**Cost.** Silent stale stored values, with no error and no log line, on rows
selected by read order rather than by any property a reader could predict. On
the partner field the value is an access anchor, and whether a stale one was
ever reachable through those rules is unmeasured; `e8ff3f09c9e^` against
`e8ff3f09c9e` is the clean before/after for anyone who needs to know.

**What would close it.** A DB-free backend whose flush is selective enough to
hold a pending set across a search — a change to `InMemoryBackend`'s contract,
not a test — would let the invariant be pinned in the tier every PR runs. Short
of that, this entry stays open as the record that the invariant is pinned by one
DB-backed test in one integration suite, and that a change to
`_field_compute.py` or to the protection path has to be checked against a real
database by hand before it lands.

## R10 — Most gate modules state their reason nowhere

**What.** `ed3f9ee3523` deleted the decision register and everything whose only
subject was it: the coverage test that required each gate to cite a record, the
coherence test over the records, the module-level record constant on every gate
module and `layer_check`'s per-contract citation. The rationale for a gate had
been moved *out* of the gate docstrings deliberately, on the grounds that the
register held it, so the deletion left most gates stating their reason nowhere
— the removal commit records that cost against itself. `44abc16805b` replaced
every dangling `ADR-NNNN` token with the decision text the record had carried,
and wrote a docstring for each gate module that had cited a record and had none.
Today **54** of the **80** gate modules under `tooling/architecture/` carry no
module docstring — a gate module being every `.py` there that is neither a test
nor a private helper.

**Evidence.** The figure above is measured from the tree by
`doc_restated_counts.py`. The guide's change protocol already says where the
reason goes — a rule whose rationale is architectural states it in the rule
itself or in the gate's own module docstring — and the gates page's inventory
names every gate without saying why any of them exists.

**Cost.** A gate that fails names a rule and not a reason, so the reader's
choices are to satisfy it blindly or to argue with a number. A gate with no
stated reason cannot be *revised* either: nobody can tell a deliberate exception
from an oversight, so its allowlist only grows, and a gate that has outlived its
reason keeps blocking because nothing says what the reason was.

**What would close it.** The figure at zero: every gate module opens with what
it holds and why, written from the gate's own failure cases now that the record
is gone. Because the figure is measured, a new gate born without its reason
moves it and fails this page's check until either the docstring or an amended
figure is written — which is the register's coverage test, reborn as a count.

---

## Adding an entry

Give it a number, a date, the evidence that makes it checkable, the cost if it
bites, and what would close it. An entry with no closing condition is a
complaint. When one is closed, say so with the date and leave it in place —
this page is a record, not a queue.
