# The gates — what is mechanically enforced, and what that is worth

> Referenced by [`ARCHITECTURE.md`](ARCHITECTURE.md). The
> architecture itself is in [`module.md`](module.md) and
> [`runtime.md`](runtime.md); this file is the operator's manual for
> the machinery that keeps them true.

This is deliberately *not* on the architecture page. A gate catalog is a tool
manual — it tells you what runs, in what order, and what each one can and cannot
see. Keeping it here is what lets the architecture page describe the system
instead of describing its own compliance.

## Running the checks

The twenty-nine blocking checkers do **not** share one CLI, and a loop that
assumes they do fails on four of them.

**Twenty-three are contract gates.** Each takes bare for a human-readable report,
`--check` for CI (exit 1 on a new violation), `--json` for a machine-readable
one:

```bash
python tooling/architecture/layer_check.py          # human-readable report
python tooling/architecture/layer_check.py --check   # CI mode: exit 1 on new violations
python tooling/architecture/layer_check.py --json     # machine-readable

python tooling/architecture/subsystem_map_check.py --check   # the subsystem map vs the tree
```

**Six are count ratchets.** Four of them — `js_function_length`,
`py_function_length`, `naming_vocabulary` and
`js_service_shape` — implement no `--check` at all, and are the four a
`--check` loop breaks on. They print a number under
`--count` and hand it to `tooling/ratchet/ratchet.py`, which owns the floor;
`js_private_access` and `js_forced_render` are the other two and have both, CI
driving them as ratchets because the pytest step already exercises their
verdicts. Run one of these bare and it reports without enforcing anything.

Twenty-three plus six is twenty-nine, and that arithmetic is the point of stating
all three. This page carried `Twenty` beside a loop of twenty-one names for as
long as nothing added them up, then `twenty-seven` on a day the workflow ran
twenty-nine. All three now derive from the workflow, by the assertion that
divides its own list.

A fourth number, **thirty, was never a state of this tree at all** — it was
produced during that same correction by measuring with an ad-hoc
`python tooling/([\w/]+)\.py` instead of the assertion's
`tooling/architecture/(\w+\.py)`, which sweeps in `tooling/ratchet/ratchet.py`:
the harness the six ratchet-driven gates pipe their counts *into*, not a
checker. It was believed and passed between sessions as fact for about an hour.
Keep it on the page as the sharpest case the rule has: a number can look
defensible, survive review, and be an artifact of the instrument that produced
it. The commit that removed the missing gate got it right for the opposite
reason — it read the count off the failing assertion's own strings rather than
counting by hand.

To reproduce the whole job, self-test first — a blocking step, because a checker
whose own logic is broken reports green over code it never read — then run both
groups in the order the workflow does:

```bash
python -m pytest tooling/architecture/ -q

for gate in layer_check mixin_coupling_check subsystem_map_check \
            package_index_check env_surface_check pool_surface_check \
            env_model_surface_check worker_thread_surface_check \
            libs_facade_check py_cycle_check js_layer_check js_cycle_check \
            named_export_coherence js_suite_parity js_layer_cohesion \
            js_import_resolution js_self_bridge js_patch_blind_facade \
            js_forced_render \
            js_public_surface js_extension_surface \
            xml_reference_coherence js_mixin_coupling; do
    python "tooling/architecture/$gate.py" --check || echo "FAILED: $gate"
done

while read -r gate floor; do
    python "tooling/architecture/$gate.py" --count \
        | xargs python tooling/ratchet/ratchet.py "$floor" --count \
        || echo "FAILED: $gate"
done <<'EOF'
js_function_length jsfunclen
py_function_length pyfunclen
naming_vocabulary  naming
js_private_access  jsprivate
js_service_shape   jsserviceshape
js_forced_render   jsforcedrender
EOF
```

**A local run judges more than CI does.** `js_public_surface`,
`js_extension_surface` and `xml_reference_coherence` are scope-aware: they judge every consumer checkout
they can see. GitHub checks out this repo alone, so CI judges only the `odoo`
scope, while the same command in an assembled workspace also judges
`enterprise`, `design-themes` and `agromarin` — and can therefore fail on a
finding that belongs to a sibling repo's own architecture workflow. Read the
`scope '<name>'` prefix on a `[FAIL]` before concluding this tree is broken.

## Quality gates beyond the boundaries

The Python boundary checker (ADR-0005) is one gate among several. The
`Architecture Boundaries` workflow runs **twenty-nine** blocking checkers — it first
runs `pytest tooling/architecture/` to self-test them, then:

| Gate | What it locks |
|------|---------------|
| `layer_check.py` | the Python layering contracts in [`module.md`](module.md#enforced-dependency-rules) |
| `mixin_coupling_check.py` | the `self`-call graph the import graph cannot see |
| `js_mixin_coupling.py` | the same for JS: the `this`-call graph across `SearchModel`'s mixin chain, which produces no import edge and no cross-module member access, so every other JS gate reads it as empty |
| `env_surface_check.py` | the Layer→runtime `env` seam, and that every reached `Environment` member exists |
| `pool_surface_check.py` | the Layer→runtime `pool` seam: private reach, member validity, and `components/` at zero |
| `env_model_surface_check.py` | the framework's string-keyed dependency on addon-owned models (`env["res.users"]`), which `core-does-not-depend-on-addons` cannot see — *which* models (exact set) **and** which subtrees may reach none. Reads six syntaxes, not just the subscript |
| `worker_thread_surface_check.py` | inline `threading.current_thread().<attr>` reads of per-request bookkeeping (`dbname`, `cursor_mode`, …), which mypy and `layer_check` cannot see |
| `libs_facade_check.py` | addon code **and every core package** importing `odoo.libs` **areas**, never their leaf modules |
| `py_cycle_check.py` | Python import cycles in the core — the direction gates cannot see them |
| `subsystem_map_check.py` | the **subsystem map above** against the actual tree |
| `package_index_check.py` | a package README's module index against the package |
| `js_layer_check.py` | the web addon's Feature-Sliced JS layers |
| `js_deployment_layers.py` | a *different* layering, in a different set of addons: `mail` files its client code by **where it runs** (`core/common/`, `discuss/core/public/`), the path segment deciding which asset bundles it lands in — so `common/` must never import from a higher layer |
| `js_cycle_check.py` | ESM import cycles across **every** addon's client source |
| `named_export_coherence.py` | `import { x }` with no matching `export` |
| `js_suite_parity.py` | the web addon's test tree against its source tree — a moved test must move with what it tests |
| `js_layer_cohesion.py` | each file filed with what it serves, not with what it resembles |
| `js_import_resolution.py` | every first-party specifier naming a real file |
| `js_self_bridge.py` | no source module resolving itself through the loader |
| `js_forced_render.py` | web core not sweeping a subtree with `render(true)` — a forced render hides reads that subscribe to nothing |
| `js_patch_blind_facade.py` | a service's own callers going through its facade |
| `js_function_length.py` | the web addon's JS function-length budget |
| `py_function_length.py` | the core's Python function-length budget — ratchets *excess lines* over 80, not the offender count, because splitting one long function raises the count while lowering the excess |
| `js_private_access.py` | the cross-module private-access budget (`_member` reached past a module) |
| `js_service_shape.py` | a service handing back an instance, not a literal |
| `js_public_surface.py` | the web addon's published JS surface, as a ratchet |
| `js_extension_surface.py` | the web addon's inheritance surface — the methods downstream subclasses override, as a ratchet |
| `naming_vocabulary.py` | the §2.4 method-naming verb vocabulary |
| `xml_reference_coherence.py` | view-arch strings (`widget=`, `js_class=`, `t-call`) against the JS registries and templates |

Four of those — `env_surface_check.py`, `pool_surface_check.py`,
`env_model_surface_check.py`, `py_cycle_check.py` — are the same argument as
`mixin_coupling_check.py`, applied to surfaces the import graph cannot see.
**What they found is architecture and lives in
[*Coupling the import graph cannot see*](module.md#coupling-the-import-graph-cannot-see):**
the runtime-channel inversion that makes the layering true of imports and false
of the runtime graph, the `init_models` ordering hazard (the
`Registry._relation_reflections` instance of it is fixed; the shape is not), the
closed set of addon-owned model names, and the ORM's freedom from cycles. What
follows here is only how those four are *driven*.

- **Scope is shared, not per-gate.** Both seam gates read their layer
  assignment from `tooling/architecture/_orm_layer_scope.py`, with a
  completeness test that forces every ORM module to be given a layer or an
  argued exemption — so the two cannot drift apart.
- **`pool_surface_check.py` ratchets three invariants**: no unsanctioned
  `pool._private` from Layers 0–2, every referenced member must exist on
  `Registry`, and `components/` must not touch `pool` at all — the runtime half
  of the purity claim `orm-components-are-pure-python` makes about imports.
- **Width is reported, not ratcheted**, on both seam gates. Layer 1 consulting
  `pool.field_inverses` is the design working; a gate firing on a 10th public
  member would punish ordinary work.
- **Two numbers, two meanings.** The private counts in the module view are the
  *unsanctioned* ones the gate pins; a run's own header prints the raw private
  width (6 and 4), which includes the members `SANCTIONED_PRIVATE` blesses. A
  run and that page will not show the same pair.
- **`env_surface_check.py` also validates that every reached member exists.**
  That is what covers the four `env.__dict__["_field_cache_memo"]` string-key
  hot paths: renaming that member is caught by nothing else — ruff is blind and
  mypy sees only the 2 plain-attribute sites — and the `except KeyError`
  fallback would silently turn the fast path into a permanent slow one.
- **`env_model_surface_check.py` pins a flat set, deliberately.** It answers
  "which models", never "who may reach them", and a package reaching an
  already-known model adds nothing. The full (package, model) cross-product
  would fire on every ordinary new reach inside a package that already reaches
  models, which is noise.
- **A model-surface gate is only as wide as the syntaxes it reads.** Until
  2026-08-09 this one read `env[...]` and the accessor map, which is most of the
  surface and not all of it: `registry[...]`/`pool[...]` (the `Registry`
  subscript hands back the model class), `env.get("...")` (a `Mapping.get`, so
  no `Subscript` node exists), `"..." in registry` (a membership test still
  names the model) and a comodel in `Many2one("res.users", ...)` all named
  models it never saw. Two of them — `ir.demo_failure` and `res.partner` — were
  absent from a set whose whole purpose is to be closed. The lesson generalises
  past this gate: a checker built on one spelling of a coupling measures that
  spelling, not the coupling, and the gap is invisible from inside the report.

`subsystem_map_check.py` and `package_index_check.py` are the two gates aimed at
the *documentation* rather than the code. The contract table is exact because a
checker enforces it; the map was prose, and prose rots. `doc_link_gate.py` proves
a referenced file *exists*; these prove a described package still *matches its
directory*.

`package_index_check.py` applies the same rule one level down, to the four
packages that document themselves per-module — `odoo/db/README.md`'s *Module
map*, `odoo/_monkeypatches/README.md`'s *Patch Index*, `odoo/http/README.md`'s
*Module map*, and `odoo/upgrade_code/README.md`'s *Module map* (whose rows are
dated script stems such as `18.1-00-sql-constraint`, not importable identifiers
— the row pattern had to stop assuming they were, or that inventory would have
matched zero rows and enforced nothing). Registration is not optional:
`PACKAGE_INDEXES` is an inclusion list, so an unregistered README would be
gated by nothing — `test_every_core_readme_is_classified` forces every core
README into `PACKAGE_INDEXES` or into `READMES_WITHOUT_AN_INDEX`.
The check is scoped to the inventory **section**, because the READMEs carry other
tables that name `.py` files: `_monkeypatches`' *Recently Removed* table names
eight patches, six of which are modules that no longer exist (`urllib3`, `lxml`,
`xlrd`, `zeep`, `pytz`, `xlwt`; the other two rows retire a *patch* from a file
that is still there). An unscoped scan reports all six as failures against a
document that is exactly right — which is what `test_section_scoping_is_load_bearing`
pins, by name rather than by count. Scoping is the whole fix, and it has to be:
those names are backticked like every other path in the tree, so a gate that
reads a backticked path as an assertion cannot tell a citation from an assertion.
The only thing that can tell them apart is *where on the page they are*.

(`cross_repo_coherence.py` is a thirtieth checker and the only one outside CI: it
runs at the `pre-push` stage via `.pre-commit-config.yaml`, because GitHub checks
out this repo alone and the check needs the sibling checkouts to compare against.
It is opt-in per clone — `pre-commit install --hook-type pre-push`.)

**Three more block without appearing above**, because they are enforced by the
`pytest tooling/architecture/` step rather than by a `--check` invocation of
their own: `js_face_boundary.py` (a specifier stepping over a face),
`js_registry_layering.py`, and `model_member_surface_check.py` (which members
the core calls on addon-owned models — the companion to
`env_model_surface_check.py`'s *which models*). Each carries a real-tree test —
`test_the_real_tree_holds_the_property_today`,
`test_the_surface_matches_the_committed_baseline` — so a violation fails the
self-test step, which is blocking. Counting them here would be a different
sentence, not a bigger number: **twenty-nine** is how many checkers CI runs as
their own step, and the self-test is the step above them.

Those three are one instance of a shape worth naming, because a second instance
turned up the same evening: `tooling/test_repo_root.py`'s `ROOT_ATTRS` was three
short — `doc_symbol_gate`, `js_deployment_layers` and `js_extension_surface` all
resolve a checkout root and were asserted by nothing. **An enumerated list is
only a gate if something independently derives the enumeration.** Both trios
were modules participating in an invariant while appearing in no list that
claimed to enumerate the participants, and neither list could report its own
gap: a hand-maintained roster is complete by assumption, and says so in exactly
the voice it would use if it were complete in fact. `subsystem_map_check.py` is
the pattern done right — it derives the tree and compares.

That distinction is worth stating rather than assuming, because it is the whole
reason the self-test runs first. `js_imports.py` is neither: it has no `main()`
and no flags, being the JS tokenizer nine of the gates above parse with — the
easiest thing in this directory to mistake for a gate, since it sits beside them
and has a `test_js_imports.py`.

Two further mechanisms keep the *non-structural* quality signals from
regressing:

- **Drift-zero count ratchet** (`tooling/ratchet/`, ADR-0006) — turns thirteen tool
  counts into one-way contracts: **mypy, ruff, ruff_docstring, c901, c901_addons, eslint, tsc, jsfunclen, pyfunclen, jsprivate, jsserviceshape, jsforcedrender and naming** (floors in
  `tooling/ratchet/baselines/`). CI fails on any increase, and — in the default
  `exact` mode — on an *un-committed* decrease too, so every cleanup is locked
  in.

  The count said "four" while the list named eight, which is the drift this page
  warns about one section up; the gate below reads the *names* and never read
  the number. `c901` was the ninth: cyclomatic complexity in `odoo/`, threshold
  `[lint.mccabe] max-complexity = 20`. It is kept out of the `ruff` aggregate
  deliberately — in one bucket a complexity fix can be masked by an unrelated
  new finding — and it gated nothing before, because `ruff.toml` selected the
  `C90` family while ignoring `C901`, its only rule.

  `c901_addons` is the tenth. Every floor above it measures
  `odoo/`, the core *package*; none measured `addons/`, where the 613 bundled
  modules and most of the business logic live, so complexity there was
  unbounded. It is a separate floor rather than a widened scope on `c901` for
  the same reason `c901` is separate from `ruff`: the two trees move for
  different reasons and by different hands, and one bucket would let an addons
  cleanup mask a core regression.

  `ruff_docstring` is the eleventh, split out of `ruff` on 2026-08-08 for the
  third application of that same argument — and the starkest. The `ruff` floor
  was 759, of which **758 were D1xx missing-docstring findings**: not debt
  accrued by accident but the measured consequence of `eff67f80316`, which
  stripped comments and docstrings from `odoo/` on purpose. An exact-match
  ratchet over one integer cannot distinguish "someone added a docstring" from
  "someone introduced a real lint defect", so those 758 units were fungible
  slack — a commit adding *N* docstrings bought room for *N* unrelated new
  findings and still totalled 759. The single genuine finding hiding in there
  (an unused `threading` import in `odoo/service/model.py`) had been invisible
  for exactly that reason; it is fixed, and **`ruff` now measures
  `--ignore D` at a hard zero**, so a new lint defect fails CI on its own.

  `ruff_docstring` is also the one floor whose direction is a real question
  rather than a target. Driving it to zero means re-adding ~758 docstrings to
  the files a deliberate commit just cleared. If docstring-free core is the
  intent, the honest change is to ignore `D1` in `ruff.toml` rather than ratchet
  it; until that is decided the floor pins the number so it cannot drift either
  way unnoticed.

  ```bash
  python tooling/ratchet/test_ratchet.py     # self-test the tool
  python tooling/ratchet/ratchet.py --list    # current floors
  ```

- **DB-backed integration gate** (`.github/workflows/integration_tests.yml`,
  ADR-0007) — boots PostgreSQL 18 and runs four suites, **each against its own
  database**: `base` (less the excluded `TestReportsRendering` and
  `TestIrModelFieldsTranslation`) on `ci_smoke`, `test_http` on `ci_http`,
  `test_orm` on `ci_orm`, and `mrp` on `ci_mrp`. So the decomposed pieces are
  verified to *behave*, not just to import cleanly.

  `test_orm` was added on 2026-08-08, the broadening this workflow's own header
  had asked for since it landed. It was by far the largest thing outside the
  lane — **1,110 test methods over 26,579 lines** under its `tests/` directory,
  and the addon written to test
  the ORM. Most of what it covers no other lane can reach, above all
  `test_domain_evaluator_parity.py`: the only check that a `Domain` means the
  same to both of its consumers, `search()` (SQL) and `filtered_domain()` (the
  in-memory predicate), including a generative suite that builds random domains
  and asserts the two evaluators agree *or both refuse*. No DB-free tier can see
  a SQL/predicate divergence.

  Adding it paid for itself on the first run, in the way this section predicts:
  `TestBackendDifferential.test_divergence_ilike_unaccent` asserted PostgreSQL's
  `ilike` folds `Café` onto `cafe` without checking that the `unaccent`
  extension is installed. Every developer database inherits it from
  `db_template`; CI's `template0` does not. The one environment that would fail
  it was the one that never ran it. It now skips on
  `registry.has_unaccent`, matching `base`'s existing idiom.

  `mrp` is the fourth, and the first suite here that is not a `test_*` addon.
  The argument for it is the one this section keeps making: a suite nobody runs
  rots silently. `3bcf5d144f9` deleted `stock.move.availability` having found
  "no consumer anywhere in the workspace", missed
  `addons/mrp/tests/test_order.py`, which asserts on it, and left that test
  erroring — every assertion after the failing line unexecuted — for as long as
  nothing ran it. It also earns its place on coverage rather than on repair:
  recursive BoM explosion, backorder splitting, multi-level procurement and
  compute chains across four models make it the deepest ORM consumer among the
  bundled addons, and installing it gives `stock`, `product`, `uom` and
  `resource` their first DB-backed exercise through a real consumer.

  What remains outside the lane is still most of the bundled test surface —
  `test_read_group` (9,203 lines, the only coverage of the five `read_group/`
  units) and `test_access_rights` (record rules and ACLs) are the next two worth
  taking, in that order.

### The limits of "enforced"

**The integration gate is the only lane that runs addon tests, and that is the
sharpest limit on the word "enforced" at the top of this page.** Every one of the
twenty-nine boundary checkers is structural and DB-free: they read import graphs,
call graphs, reached-member sets and documents. A change can satisfy all
twenty-nine, and Tier 1 and Tier 2, and still be wrong — renaming `OrmCore`'s
slots (`cache`/`engine` → `_cache`/`_engine`) broke two DB-backed addon tests in
2026-08 while every gate and both DB-free tiers stayed green, because nothing
those gates read had changed. Read a green boundary job as "the structure holds", never as "the
framework works".

The corollary is that a suite outside this lane is a suite nobody runs. When you
add a test addon, add it to the lane — **with its own database.** The suites
genuinely interfere: `test_http` depends on `mail`, whose `res_partner_views.xml`
inherits `base.view_res_partner_filter` anchored on `<filter name="inactive">`,
and base's `test_hard_reset_from_file_still_works` overwrites that view with a
minimal `<search>`. The write re-validates the children, so `-i base` is 5/5
green while `-i base,test_http` raises `ValidationError` — running only that one
test class. The base test is fragile by construction, since it mutates a shared
core view and therefore passes only while nothing inherits it; one database per
suite is what stops the next addon added here from tripping it.

ADR-0009 records how these gates were wired shut (mainline `push:` triggers,
full façade scope, re-measured floors) after an audit found each one bypassable.

## Known boundary exceptions

**None that are debt.** The two pinned rules both belong to
`core-does-not-depend-on-addons` and are deliberate, permanent, and scoped to
`odoo.service`: `service/_threaded.py` and `service/_worker.py` call
`IrCron._process_jobs` / `IrJob._process_jobs`, `@staticmethod` entry points that
open their own cursor because they run *before* a registry exists for the
database, so there is no `env` to route through. Both imports are deferred to
call time, and no override of either exists anywhere in
`odoo`/`enterprise`/`agromarin`. They are pinned rather than allow-listed so they
stay visible in every report.

The eight original contracts remain clean at zero; the exceptions surfaced by the
checker's first run have all been paid down:

- **Asset pipeline** (`esbuild`, `esm_bridges`, `esm_graph`, `esm_registry`)
  relocated from `libs/` to `odoo/tools/assets/` (ADR-0004). `asset_log` remains
  in `libs/` and is genuinely dependency-free — logging helpers over a
  logger-name string. `constants` was kept alongside it on the same reasoning
  and should not have been: it held 24 import-map asset paths (two of them into
  the optional `spreadsheet` and `survey` addons), the ORM prefetch and vacuum
  limits, and the `ir.cron`/`ir.job` NOTIFY channel names. Every consumer was in
  `tools/`, `orm/`, `addons/base` or an addon tree; none was a generic utility.
  `libs-is-dependency-free` was green throughout, because it is an import rule
  and a string literal produces no import edge. Split on 2026-08-09 into
  `tools/assets/constants.py`, `orm/primitives.py` and `tools/constants.py`, and
  the libs module deleted. The import-map builder, its only reader inside
  `libs/`, moved to `tools/assets/` with it — it is
  `tools/assets/import_map.py` now. (Neither old path is written here as a
  backticked path: in this repo that asserts the file exists, and
  `test_named_source_paths_exist` checks it.)
- **`libs/filesystem/osutil.py`** no longer imports `odoo.release`; the Windows
  service name is passed in by the caller (ADR-0004).
- **Layer-1 → Layer-2 deferred `BaseModel` imports** in `orm/domain/ast.py` and
  `orm/fields/relational/` (since split into a package: `_base`, `many2one`,
  `one2many`, `many2many`) replaced by the `orm/_recordset.py` injection seam.
  What remains of `BaseModel` in those modules is `if TYPE_CHECKING:`-guarded
  annotation, which never executes (ADR-0001).
- **`MODULE_UNINSTALL_FLAG`** moved from `addons/base/models/ir_model_common` to
  `orm/primitives` (the ORM's `unlink` branches on it, so the ORM owns it); it is
  re-exported from the addon for the `ir_model*` / `ir_module` code that sets it.
- **`format_number`, `intersperse`, `split`, `parse_grouping`** moved from
  `addons/base/models/res_lang` to `libs/locale/number_format`. They are pure and
  DB-free, and `tools/formatting.py` was reaching into an addon twice to call
  them. Locale data now arrives through a `LocaleConventions` **Protocol**, so
  `libs/` stays dependency-free while the addon's `LangData` satisfies it
  structurally.

