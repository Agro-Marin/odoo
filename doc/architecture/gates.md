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

The twenty-four blocking checkers do **not** share one CLI, and a loop that
assumes they do fails on three of them.

**Twenty are contract gates.** Each takes bare for a human-readable report,
`--check` for CI (exit 1 on a new violation), `--json` for a machine-readable
one:

```bash
python tooling/architecture/layer_check.py          # human-readable report
python tooling/architecture/layer_check.py --check   # CI mode: exit 1 on new violations
python tooling/architecture/layer_check.py --json     # machine-readable

python tooling/architecture/subsystem_map_check.py --check   # the subsystem map vs the tree
```

**Four are count ratchets** — `js_function_length`, `naming_vocabulary`,
`js_service_shape` implement no `--check` at all. They print a number under
`--count` and hand it to `tooling/ratchet/ratchet.py`, which owns the floor;
`js_private_access` has both, and CI drives it as a ratchet because the pytest
step already exercises its cross-layer verdict. Run one of these bare and it
reports without enforcing anything.

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
            js_public_surface xml_reference_coherence; do
    python "tooling/architecture/$gate.py" --check || echo "FAILED: $gate"
done

while read -r gate floor; do
    python "tooling/architecture/$gate.py" --count \
        | xargs python tooling/ratchet/ratchet.py "$floor" --count \
        || echo "FAILED: $gate"
done <<'EOF'
js_function_length jsfunclen
naming_vocabulary  naming
js_private_access  jsprivate
js_service_shape   jsserviceshape
EOF
```

**A local run judges more than CI does.** `js_public_surface` and
`xml_reference_coherence` are scope-aware: they judge every consumer checkout
they can see. GitHub checks out this repo alone, so CI judges only the `odoo`
scope, while the same command in an assembled workspace also judges
`enterprise`, `design-themes` and `agromarin` — and can therefore fail on a
finding that belongs to a sibling repo's own architecture workflow. Read the
`scope '<name>'` prefix on a `[FAIL]` before concluding this tree is broken.

## Quality gates beyond the boundaries

The Python boundary checker (ADR-0005) is one gate among several. The
`Architecture Boundaries` workflow runs **twenty-four** blocking checkers — it first
runs `pytest tooling/architecture/` to self-test them, then:

| Gate | What it locks |
|------|---------------|
| `layer_check.py` | the Python layering contracts in [`module.md`](module.md#enforced-dependency-rules) |
| `mixin_coupling_check.py` | the `self`-call graph the import graph cannot see |
| `env_surface_check.py` | the Layer→runtime `env` seam, and that every reached `Environment` member exists |
| `pool_surface_check.py` | the Layer→runtime `pool` seam: private reach, member validity, and `components/` at zero |
| `env_model_surface_check.py` | the framework's string-keyed dependency on addon-owned models (`env["res.users"]`), which `core-does-not-depend-on-addons` cannot see — *which* models (exact set) **and** which subtrees may reach none |
| `worker_thread_surface_check.py` | inline `threading.current_thread().<attr>` reads of per-request bookkeeping (`dbname`, `cursor_mode`, …), which mypy and `layer_check` cannot see |
| `libs_facade_check.py` | addon code **and every core package** importing `odoo.libs` **areas**, never their leaf modules |
| `py_cycle_check.py` | Python import cycles in the core — the direction gates cannot see them |
| `subsystem_map_check.py` | the **subsystem map above** against the actual tree |
| `package_index_check.py` | a package README's module index against the package |
| `js_layer_check.py` | the web addon's Feature-Sliced JS layers |
| `js_cycle_check.py` | ESM import cycles across **every** addon's client source |
| `named_export_coherence.py` | `import { x }` with no matching `export` |
| `js_suite_parity.py` | the web addon's test tree against its source tree — a moved test must move with what it tests |
| `js_layer_cohesion.py` | each file filed with what it serves, not with what it resembles |
| `js_import_resolution.py` | every first-party specifier naming a real file |
| `js_self_bridge.py` | no source module resolving itself through the loader |
| `js_patch_blind_facade.py` | a service's own callers going through its facade |
| `js_function_length.py` | the web addon's JS function-length budget |
| `js_private_access.py` | the cross-module private-access budget (`_member` reached past a module) |
| `js_service_shape.py` | a service handing back an instance, not a literal |
| `js_public_surface.py` | the web addon's published JS surface, as a ratchet |
| `naming_vocabulary.py` | the §2.4 method-naming verb vocabulary |
| `xml_reference_coherence.py` | view-arch strings (`widget=`, `js_class=`, `t-call`) against the JS registries and templates |

Four of those — `env_surface_check.py`, `pool_surface_check.py`,
`env_model_surface_check.py`, `py_cycle_check.py` — are the same argument as
`mixin_coupling_check.py`, applied to surfaces the import graph cannot see.
**What they found is architecture and lives in
[*Coupling the import graph cannot see*](module.md#coupling-the-import-graph-cannot-see):**
the runtime-channel inversion that makes the layering true of imports and false
of the runtime graph, the `Registry._relation_reflections` ordering hazard, the
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

(`cross_repo_coherence.py` is a twenty-fifth checker and the only one outside CI: it
runs at the `pre-push` stage via `.pre-commit-config.yaml`, because GitHub checks
out this repo alone and the check needs the sibling checkouts to compare against.
It is opt-in per clone — `pre-commit install --hook-type pre-push`.)

Two further mechanisms keep the *non-structural* quality signals from
regressing:

- **Drift-zero count ratchet** (`tooling/ratchet/`, ADR-0006) — turns ten tool
  counts into one-way contracts: **mypy, ruff, c901, c901_addons, eslint, tsc, jsfunclen, jsprivate, jsserviceshape and naming** (floors in
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

  `c901_addons` is the tenth and the newest. Every floor above it measures
  `odoo/`, the core *package*; none measured `addons/`, where the 615 bundled
  modules and most of the business logic live, so complexity there was
  unbounded. It is a separate floor rather than a widened scope on `c901` for
  the same reason `c901` is separate from `ruff`: the two trees move for
  different reasons and by different hands, and one bucket would let an addons
  cleanup mask a core regression.

  ```bash
  python tooling/ratchet/test_ratchet.py     # self-test the tool
  python tooling/ratchet/ratchet.py --list    # current floors
  ```

- **DB-backed integration gate** (`.github/workflows/integration_tests.yml`,
  ADR-0007) — boots PostgreSQL 18 and runs two suites, **each against its own
  database**: `base` (less the excluded `TestReportsRendering` and
  `TestIrModelFieldsTranslation`) and `test_http`. So the decomposed pieces are
  verified to *behave*, not just to import cleanly.

### The limits of "enforced"

**The integration gate is the only lane that runs addon tests, and that is the
sharpest limit on the word "enforced" at the top of this page.** Every one of the
twenty-four boundary checkers is structural and DB-free: they read import graphs,
call graphs, reached-member sets and documents. A change can satisfy all
twenty-four, and Tier 1 and Tier 2, and still be wrong — renaming `OrmCore`'s
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
  relocated from `libs/` to `odoo/tools/assets/` (ADR-0004). The dependency-free
  helpers it builds on (`asset_log`, `constants`) remain in `libs/`.
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

