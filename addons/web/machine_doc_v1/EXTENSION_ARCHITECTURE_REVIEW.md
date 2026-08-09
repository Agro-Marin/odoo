# Extension Architecture Review — `addons/web` JavaScript

Status: **Findings and proposal. No production code changed.**
First draft 2026-08-09; **revised the same day after an adversarial re-check that
corrected every headline number and retracted one finding outright.**
Scope: `addons/web/static/src`, measured against its consumers in `odoo/addons`,
`enterprise`, `agromarin`, `design-themes`.

> This document does not restate `ARCHITECTURE.md`, `STATE_MANAGEMENT.md`,
> `ESM_BUNDLING.md` or `DIRECTORY_MAP.md`. It covers one question those don't:
> **how other modules extend `web`, and what that costs.**
>
> **Read *Verification* (below) before quoting anything here.** The first draft's
> figures were undercounts produced by a scanner that did not walk inheritance
> chains, and one finding (F5) was withdrawn as unsound.

---

## Summary

`web` has a governed **import** boundary and, inside `model/`, a governed
**private-access** boundary. It has no governed **inheritance** boundary — and
inheritance is how the fork extends it.

| Surface | Size | Declared? | Gated? |
|---|---|---|---|
| Import specifiers (`@web/...` from outside) | 235 pinned | yes — `public_surface_web.txt` | yes, shrink-only |
| Private reaches inside `model/relational_model/` | 4 contract files | yes — array + typedef | yes, ratchet + conformance |
| **Method overrides by downstream subclasses** | **440 points, 1,101 subclasses, 144 base classes** | **no** | **no** |

This was tested, not asserted. In two git worktrees at the same commit
(`891d617a711`), differing only by renaming `beforeExecuteActionButton` →
`beforeRunActionButton` inside `web` and leaving all consumers untouched:

```
pristine : 3 failed, 909 passed, 1 skipped, 178 subtests    tooling/architecture
renamed  : 3 failed, 909 passed, 1 skipped, 178 subtests    ← identical failure set
tsc      : 2100 errors == the committed ratchet floor        ← lane passes
```

Zero new failures. 19 classes across `odoo/addons` and `enterprise` override
that method; **18 of the 19 have no test that references them at all**, and
`enterprise` is never checked out by odoo's CI (all 18 `actions/checkout` steps
take no `repository:`), so half the breakage is invisible to that CI by
construction.

The fix does not need inventing. `public/interaction.js` shows what a narrow,
declarative extension contract looks like at 237 subclasses, and
`model/relational_model/record_contract.js` shows how this fork declares and
gates a surface. The proposal is to point the second at the first.

---

## Verification

The first draft was re-checked adversarially. What that changed:

### Retracted

**F5 — "the extension model is a performance constraint."** The draft argued
that `render_bench`'s *46% V8 compile + native + gc* meant bundle parsing
dominates a cold render, so shipping less code was the lever and inheritance
blocked it. **This is wrong.** `render_bench`'s `COLD` navigates to
`res.currency` and back *inside an already-loaded SPA* (`COLD_JS` in the script)
— the bundle was parsed long before `t0`. That 46% is lazy function
compilation, IC/optimisation and GC during a navigation, not bundle parse.
Code splitting affects **first page load**, which `render_bench` does not
measure and which nothing in this repo currently measures. The synthesis
conflated two different quantities and is withdrawn. What survives is only what
`LAZY_VIEW_LOADING.md` already said, and its decision stands unchanged.

### Corrected — every headline count was an undercount

The first scanner counted only **direct** subclasses of a class defined in
`web`. It therefore missed `A extends B extends FormController`, `extends
formView.Controller` (descriptor property), and `extends Mixin(WebClass)`. A
v2 resolver that walks import/re-export chains and handles all three forms:

| Figure | Published | Measured | |
|---|---|---|---|
| cross-addon subclasses | 877 | **1,101** | +26% |
| override points | 386 | **440** | +14% |
| base classes subclassed | 136 | **144** | |
| single-use points | 59% | **54%** (238/440) | |
| private override points | 23 (31 sites) | **25 (38 sites)** | |
| `Interaction` subclasses | 187 | **237** | |
| `FormController` / `ListController` / `ListRenderer` subclasses | 51 / 47 / 40 | **64 / 60 / 55** | |
| `setup()` sites (non-`Interaction`) | 315 of 885 | **389 of 1,089** | |
| contract-density ratio (`Interaction` vs backend) | 18.7 vs 1.8 | **23.7 vs 2.0** | contrast strengthened |

Forms captured by v2 that v1 missed: 37 `descriptor.Property` bases, 67
`Mixin(Base)` bases.

An independent cross-check — counting `super.<name>()` call sites in consumer
code, which shares no code with either scanner — reconciles:
`super.beforeExecuteActionButton()` appears 17 times; v2 attributes 13 to
`FormController` and 3 to `ListController` (both define it), and the 17th is
`FsmProjectTaskFormController`, whose chain runs through `@project/*` — an alias
absent from `tsconfig.json`, so the walk cannot follow it. **Known residual
blind spot: 126 aliases (1,249 import sites) are not in `tsconfig.json` paths,
so any chain through them breaks.** The true figures are therefore floors.

### Also corrected

- **"56 architecture gates fail at HEAD"** — an artifact of running pytest in a
  `/tmp` worktree with no `node_modules`; several gates shell out to `.mjs`
  helpers. With `node_modules` linked the real baseline is **3 failures**, all in
  `test_architecture_doc*` (restated-count drift), none related to this work.
  The first A/B run was invalid for the same reason — arm B looked *better* than
  arm A because only B had the symlink.
- **The missing-alias finding was wrong as first stated.** It predicted TS2307
  errors; the full program reports **zero**. A direct probe proves the aliases
  genuinely don't resolve (`TS2307` on a `@ts-check`ed probe file), but the files
  importing them — e.g. `todo_list_view.js` — **carry no `@ts-check`**, so they
  are not checked at all. This is a prerequisite for P5, not a live bug.
- **P4's ordering rationale was wrong.** The draft claimed `extends` chains
  "order by import graph — whoever evaluates first wins". Single inheritance is
  deterministic; that hazard belongs to `patch()`, not `extends`. The real
  `extends` limitation is different and is restated in P4.
- **Addon-on-addon inheritance is smaller and more legitimate than implied**:
  94 of 1,101 chains (8.5%) reach `web` through a non-web intermediate, and the
  common shape is genuine domain layering
  (`Many2ManyTagsAvatarEmployeeField → …UserField → …AvatarField`), not forced
  coupling.
- One of my own verification greps was itself broken: `[\w$]` inside a bracket
  expression matches the literals `\`, `w`, `$`, so an early check reported
  "`extends X.Y` = 0 sites" when 29 non-test files use it. It is fixed above.

### Survived unchanged

- `@ts-check` on **756 of 763** files — exact.
- `any` in JSDoc type positions — published 2,447; a stricter JSDoc-only count
  gives **2,480**, i.e. the published figure was slightly conservative. Only 13
  matches came from outside JSDoc.
- The twelve named `list_*` helpers all exist.
- `Interaction` has exactly **10** override points.
- The private-access gate structurally cannot see this surface: its `ACCESS`
  regex excludes `super.` explicitly (`(?!this\b|super\b|props\b)`) and it scans
  only `addons/web/static/src`.

---

## Findings

### F1 — The extension surface is undeclared

1,101 cross-addon subclasses of 144 `web` base classes, overriding **440
distinct `(base, method)` points** — 563→ `odoo/addons`, 307→ `enterprise`,
7→ `agromarin` in the v1 scope split; v2 totals are higher but distributed
similarly.

Those 440 points are the real public API of web's JS. They are written down
nowhere and checked by nothing. `js_public_surface.py`'s own docstring names the
gap — *"`web` has no declared API"* — but its remedy pins **module specifiers**,
a strictly weaker statement: it guarantees `@web/views/form` keeps existing, not
that `beforeExecuteActionButton` does.

**Proven by experiment** (see *Summary*): a rename passes the whole architecture
suite and the typecheck lane.

### F2 — 54% of that API serves exactly one caller

238 of 440 points are reached by exactly one subclass. Excluding `Interaction`,
236 of 430.

A method overridden once is not an extension point; it is a place where one
addon reached for the nearest lever. Each still pins the base's shape, because
nothing distinguishes it from a deliberate contract.

**Counter-argument worth recording**: `odoo/addons` is upstream code written for
a broad ecosystem, so some single-use points are deliberate generality rather
than accident. That is a real consideration for P3 — but it is a *decision to
take per point*, which is precisely what no one can currently do, because the
list does not exist.

### F3 — `Interaction` already demonstrates the better model

| base | subclasses | override points | subclasses per point |
|---|---|---|---|
| `Interaction` (`public/`) | 237 | 10 | **23.7** |
| everything else (backend) | 864 | 430 | 2.0 |

`Interaction` carries 237 subclasses on a 10-point contract because its
extension surface is **declarative data**: `static selector`, `static
selectorHas`, `dynamicContent`, `dynamicSelectors`. A subclass declares *what*
it matches; the framework owns *how*. The two behavioural hooks it exposes
(`start`, `destroy`) are lifecycle, named as such.

*Caveat*: only 2 of `Interaction`'s 10 points are single-use vs 236 of 430 in
the backend — a real contrast, but 10 points is a small denominator, so treat
the ratio as illustrative rather than statistical.

### F4 — A third of all inheritance exists to run extra constructor code

`setup()` is **389 of 1,089** backend override sites across 70 classes:
`FormController` 45, `ListController` 43, `KanbanController` 33, `ListRenderer`
26, `KanbanRenderer` 21, `X2ManyField` 17.

Only ~9% of subclasses are setup-*only*, so this is not "most subclasses are
trivial". But the single most-demanded thing from every base class is *run my
hooks during setup, then carry on*.

### F5 — *(withdrawn — see Verification)*

### F6 — Type checking stops exactly at the boundary the contract crosses

This replaces the draft's weaker "2,447 `any`s" framing, which was true but not
the point.

`addons/web` is well typed internally: 756 of 763 files carry `@ts-check`.
Outside it, essentially nothing does:

| tree | files with `@ts-check` |
|---|---|
| `addons/web` | 756 |
| all other `odoo/addons` JS (4,956 files) | **40** |
| `enterprise` | **10** |

So the 440 override points are unchecked **from the side that consumes them**,
by construction. Verified concretely: none of the 7 `odoo/addons` files broken by
the rename experiment carries `@ts-check`, which is why tsc reported no new
errors. The 2,480 internal `any`s matter, but they are a second-order problem
next to consumers that are not compiled at all.

### F7 — `ListRenderer` is a god component that survived its own decomposition

1,333 lines, ~70 members, **55** downstream subclasses, 54 `any`s. `views/list/`
holds twelve extracted helpers — `list_focus`, `list_sorting`, `list_selection`,
`list_styling`, `list_virtualization`, `list_grid_state`, `list_keyboard_nav`,
`list_keyboard_edit`, `list_optional_fields`, `list_column_utils`,
`list_group_rendering`, `list_aggregates` — and the renderer still orchestrates
every one as a single class. The extraction moved the code without moving the
*coupling*.

### F8 — 25 private override points remain (38 sites)

`SearchModel._importState`, `ConfirmationDialog._confirm`,
`CogMenu._registryItems`, `RelationalModel._loadData`, `DynamicList._load` /
`_selectDomain` / `_removeRecords`, and others. Small, bounded, closable now.

### F9 *(new)* — The consumers of this surface are untested

Of the 19 classes overriding `beforeExecuteActionButton`, **18 have no test
anywhere that so much as names them**. Combined with odoo's CI never checking
out `enterprise`, the practical safety net for a `web` API change is: web's own
suite (which does catch a rename, because web tests patch `FormController`
directly), and nothing else.

---

## Proposals

Ordered by value ÷ cost. P1–P3 are independent and individually shippable;
P4–P6 depend on P1 having produced the worklist.

**P1 is implemented** (`a131d2e1c6e`) — `js_extension_surface.py` +
`extension_surface_web.txt`, pinned at 448 points over 1,896 sites, wired into
all six inventory points and green.

**P5 step 1 is implemented** (`8b4f47004de`) — the `tsconfig.json` alias map
completed, at a measured cost of zero errors, plus a test that stops it rotting.

P2, P3, P4 and P6 are unstarted. P5 steps 2–3 (turning `@ts-check` on outward,
then typing the seams) are now unblocked.

### P1 — Declare and gate the extension surface *(done)*

`tooling/architecture/js_extension_surface.py` + `extension_surface_web.txt`,
built to the shape of `js_public_surface.py`: per-consumer-scope provenance,
shrink-only both directions, empty-tree refusal test.

```
FormController.beforeExecuteActionButton    enterprise(8) odoo(5)
KanbanController.createRecord               enterprise(10) odoo(1)
ListRenderer.getColumns                     odoo(4)
```

`createRecord` is worth reading twice: ten of eleven overrides are in
`enterprise`. A rename judged from `odoo/addons` alone looks nearly free and is
not — and odoo's CI cannot tell you otherwise, because `enterprise` is not on
disk there.

The scanner must walk transitive chains and handle `descriptor.Property` and
`Mixin(Base)` bases; a direct-subclass-only implementation undercounts by ~26%,
as this document's own first draft demonstrates. Fixing the **126 missing
tsconfig aliases** is a prerequisite for the chain walk to be complete.

**Do not classify entries in the first pass.** Provenance only.

### P2 — Close the 25 private override points

Per point: **promote** (drop the underscore — `_importState`/`exportState` is a
matched pair, one public and one not, which is an inconsistency rather than a
design) or **replace** (declared hook, convert the callers). Then extend
`js_private_access.py`, which today (a) scans only `addons/web/static/src` and
(b) explicitly excludes `super.`, to cover cross-addon overrides at a hard zero.

### P3 — Retire the single-use surface

238 points serve exactly one subclass. Per point: **inline**, **promote**, or
**generalize**. Run per base class, largest first — `FormController` 64,
`ListController` 60, `ListRenderer` 55, `KanbanController` 45, `X2ManyField` 36.
Weigh F2's counter-argument (deliberate upstream generality) per point.

### P4 — Give the hot override points a declarative form

For the highest-traffic behavioural seams — `beforeExecuteActionButton` (13),
`KanbanController.createRecord` (11), `X2ManyField.onAdd`,
`SelectionField.options` — registry-backed contribution points that the base's
default implementation consults.

```js
registry.category("form_controller.before_action_button").add("my_addon", {
    sequence: 20,
    async handler(ctx) { /* … */ },
});
```

The corrected rationale — `extends` is deterministic, so ordering is *not* the
problem:

- **Independent extenders cannot compose.** Two addons needing the same seam on
  the same view must either have one subclass the other (an inter-addon
  dependency) or fall back to `patch()` (which *is* load-order dependent).
  Contributions compose by construction, and `sequence` states priority
  explicitly — the idiom `ViewCompiler._sortCompilers()` already reached for.
- **No import-time base dereference**, which keeps the seam splittable.
- **A validatable contract**, via `registry.addValidation()`.

Keep `extends` working: the default implementation *is* the registry walk, so an
overriding subclass still wins and conversion is per-addon and reversible.

### P5 — Extend type checking to the consuming side

The draft proposed typing web's internal seams. F6 reframes the priority: the
seams are unchecked from **outside**, where 4,956 files carry 40 `@ts-check`
markers between them. Order of work:

1. Add the **126 missing aliases** to `tsconfig.json` — without them a
   consumer's imports cannot resolve at all.
2. Turn on `@ts-check` for the addons that subclass `web` most (`project`,
   `mail`, `sale`, `stock`), so an override that breaks its contract fails a
   lane instead of a runtime.
3. Then type the seams themselves (`archInfo`, controller `model`, `_uiHooks`),
   using `record_contract.js`'s runtime-array + typedef + agreement-gate idiom.

### P6 — Finish decomposing `ListRenderer`

Move the twelve helper groupings behind named sub-objects the template addresses
directly. **Sequence last**: before P1/P3, 55 subclasses reach into an aggregate
nobody has declared and the refactor cannot be verified against anything.

---

## Explicitly not proposed

- **Fork-wide lazy view loading** — decided against in `LAZY_VIEW_LOADING.md`;
  the draft's attempt to reopen the ROI question via `render_bench` was unsound
  (see *Verification*) and is withdrawn. The decision stands.
- **View-teardown optimisation** — investigated and rejected; the ~9% is
  vendored blockdom.
- **Micro-optimising the render path** — `render_bench`'s header records two
  proposals written off call counts alone, both wrong. Nothing here is justified
  by a call count.
- **A TypeScript migration** — P5 step 2 buys most of the benefit at a fraction
  of the cost.

---

## Implementation notes (P1)

Shipped as `tooling/architecture/js_extension_surface.py`, modelled on
`js_public_surface.py`: per-consumer-scope provenance, shrink-only in both
directions, refuses an empty tree, `--check` / `--json` / `--update`.

**Pinned at 448 points over 1,896 sites, 242 single-use, 112 owner classes,
1,175 subclasses** — carried in a `doc_measured` MEASURED block so the figures
cannot rot in prose. That is the fourth distinct number this document has
reported for the same quantity (386 → 440 → 451 → 448); the block exists so
there is no fifth written by hand.

Three things the implementation changed about the measurement:

- **Aliases come from the addon layout, not `tsconfig.json`.** Every addon `X`
  publishes `@X/*` as `<root>/addons/X/static/src/*`. Deriving them this way
  resolves the 152 aliases (1,961 import sites) `tsconfig.json` omits, so
  chains through `@project/*` and friends are no longer lost. This is why the
  gate measures more than the scratch resolver did.
- **web's own tests are not surface.** Scoping "is this web?" to `static/src`
  made `web/static/tests/` look like a downstream consumer: 3 points and 7 sites
  entered the first pin that way, and — worse — the pin then drifted whenever
  anyone edited a web test. The predicate is now the addon, matching
  `js_public_surface.py`. `test_a_subclass_in_webs_own_tests_is_not_surface`
  pins it.
- **`/lib/` is no longer a blanket exclusion.** `static/src/core/lib/` and
  `static/src/libs/` are first-party (`@web/libs/bootstrap` has four importers).
  Nothing under them declares a class *yet*, which is precisely how the loose
  match would have gone unnoticed once one did.

**End-to-end check.** Renaming `beforeExecuteActionButton` in
`form_controller.js` — the change that passed the entire architecture suite and
the typecheck lane — now exits 1 and reports it three ways: new drift in the
`odoo` scope, new drift in `enterprise`, and an orphaned pin naming a method no
web class declares. Restoring the file returns exit 0.

The two mutations that matter were verified to be caught: crippling the
transitive walk to direct-parent-only, and dropping the descriptor-property
form, each make `test_a_grandchild_is_attributed_to_the_web_ancestor` and
`test_a_descriptor_property_base_resolves` fail rather than silently measure
less.

### P5 step 1 — done, and it was free after all

**Correction.** An earlier revision of this document said adding the missing
aliases surfaced "roughly ten" type errors and therefore needed a decision. That
was wrong, and wrong for a reason worth recording: the two `tsc` runs it compared
were ten minutes apart on a workspace another session was actively committing
to, and the *baseline* moved 2,100 → 2,108 between them. The +10 was that drift,
not the change.

Re-measured properly — a worktree placed as a **sibling of `enterprise/`** so
the `../enterprise` path mappings still resolve, both arms against the one
frozen commit:

```
baseline           2105 errors
+ all aliases      2105 errors     identical sets in BOTH directions
```

Zero. And necessarily so, for the reason F6 already established: the files
importing those aliases carry no `@ts-check`, so resolving their imports compiles
nothing new. The map can be completed for free *before* `@ts-check` goes outward,
rather than being hit as a wall afterwards.

Landed as `8b4f47004de`: 169 aliases added (43 of 214 were mapped), 7 dropped
that mapped nothing and were imported by nobody. `@test_mail/*` is kept despite
the same absent directory — nine files reach its helpers through
`@test_mail/../tests/…`, which resolves textually, and the first version of the
guard test would have deleted it. `tooling/typecheck/test_tsconfig_paths.py`
keeps the map honest from here.

**The typecheck scope gates are red at HEAD**, on
`keep_last_abort.test.js` and `superseded_load.test.js` — another session's
commits, and unrelated: both import only `@odoo/*` and `@web/*` (neither added
here), and the errors are `Property 'resolve' does not exist on…`, a type-shape
issue rather than a resolution one.

## Reproducing

```bash
# transitive resolver (handles chains, descriptor and mixin bases)
python resolve2.py                     # scratch script, not committed

# independent cross-check, shares no code with the above
grep -roE 'super\.[A-Za-z_$][\w$]*\s*\(' <consumer trees>   # exclude minified

# the gate experiment
git worktree add --detach A HEAD && git worktree add --detach B HEAD
ln -s <repo>/node_modules A/node_modules   # REQUIRED — several gates shell out to .mjs
ln -s <repo>/node_modules B/node_modules
sed -i 's/beforeExecuteActionButton/beforeRunActionButton/g' B/addons/web/static/src/views/{form/form_controller,multi_record_controller,list/list_controller,settings/settings_form_controller}.js B/addons/web/static/src/fields/relational/x2many_dialog.js
(cd A && pytest tooling/architecture -q --tb=no) ; (cd B && pytest tooling/architecture -q --tb=no)
```

Run the arms **sequentially and identically configured**. The first attempt at
this comparison was invalid because only one arm had `node_modules`.
