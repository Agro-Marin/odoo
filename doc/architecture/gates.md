# The gates — what is mechanically enforced, and what that is worth

> Referenced by [`ARCHITECTURE.md`](ARCHITECTURE.md). The architecture is in
> [`module.md`](module.md) and [`runtime.md`](runtime.md); this file is the
> operator's manual for the machinery that keeps them true.

## Running the checks

The thirty-two blocking checkers do **not** share one CLI, and a loop that
assumes they do fails on four of them.

**Twenty-six are contract gates.** Each takes bare for a human-readable
report, `--check` for CI (exit 1 on a new violation), `--json` for a
machine-readable one:

```bash
python tooling/architecture/layer_check.py           # human-readable report
python tooling/architecture/layer_check.py --check   # CI mode: exit 1 on new violations
python tooling/architecture/layer_check.py --json    # machine-readable
```

**Six are count ratchets.** `js_function_length`, `py_function_length`,
`naming_vocabulary` and `js_service_shape` implement no `--check` at all — the
four a `--check` loop breaks on. They print a number under `--count` and hand it
to `tooling/ratchet/ratchet.py`, which owns the floor. `js_private_access` and
`js_forced_render` also implement `--check`, but CI drives them as ratchets, so
they belong to this group. Run any of the six bare and it reports without
enforcing.

Twenty-six plus six is thirty-two. All three figures derive from the
workflow, by the assertion that divides its own list; so does the membership of
the loop below (`test_the_reproduce_loop_is_exactly_the_contract_gates`) — an
enumerated list is a gate only when something independently derives the
enumeration.

Reproduce the whole job. Self-test first, blocking, because a checker whose own
logic is broken reports green over code it never read; then both groups in the
workflow's order:

```bash
python -m pytest tooling/architecture/ -q

for gate in layer_check mixin_coupling_check subsystem_map_check \
            package_index_check env_surface_check pool_surface_check \
            env_model_surface_check worker_thread_surface_check \
            libs_facade_check py_cycle_check js_layer_check js_cycle_check \
            js_deployment_layers named_export_coherence js_suite_parity \
            js_layer_cohesion js_import_resolution js_self_bridge \
            js_patch_blind_facade js_public_surface js_extension_surface \
            js_env_config_surface js_arch_info_surface js_field_record_surface \
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

# Two gates are addon-scoped and run twice, once per governed addon. The loop
# above carries no argument column, so mail's scopes are explicit:
python tooling/architecture/js_function_length.py --addon mail --count \
    | xargs python tooling/ratchet/ratchet.py jsfunclen_mail --count
python tooling/architecture/js_service_shape.py --addon mail --count \
    | xargs python tooling/ratchet/ratchet.py jsserviceshape_mail --count
```

**A local run judges more than CI does.** `js_public_surface`,
`js_extension_surface` and `xml_reference_coherence` are scope-aware: they judge
every consumer checkout they can see. GitHub checks out this repo alone, so CI
judges the `odoo` scope only, while the same command in an assembled workspace
also judges `enterprise`, `design-themes` and `agromarin` — and can fail on a
finding belonging to a sibling repo's own workflow. Read the `scope '<name>'`
prefix on a `[FAIL]` before concluding this tree is broken.

## Quality gates beyond the boundaries

The Python boundary checker (ADR-0005) is one gate among several. The
`Architecture Boundaries` workflow runs **thirty-two** blocking checkers, after
`pytest tooling/architecture/` self-tests them:

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
| `subsystem_map_check.py` | the **subsystem map** in the module view against the actual tree |
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
| `js_arch_info_surface.py` | the `archInfo` keys the view compiler writes into *generated template source*, where they are strings until OWL compiles them and no type, linter or member gate can follow them; plus each view type's parser against what its own directory reads |
| `js_field_record_surface.py` | what field widgets reach through `props.record` — `standardFieldProps` hands all 83 members of a live `RelationalRecord` to 155 widgets, and a prop read is neither an import nor a class member, so no other gate sees it |
| `js_env_config_surface.py` | the keys read out of `env.config`, web's ambient per-action bag — inherited through the component tree, so it is neither an import nor a class member and the two surface gates above are blind to it |
| `naming_vocabulary.py` | the §2.4 method-naming verb vocabulary |
| `xml_reference_coherence.py` | view-arch strings (`widget=`, `js_class=`, `t-call`) against the JS registries and templates |

### The four surface gates

`env_surface_check.py`, `pool_surface_check.py`, `env_model_surface_check.py`
and `py_cycle_check.py` are `mixin_coupling_check.py`'s argument applied to
surfaces the import graph cannot see. **What they found is architecture and
lives in [*Coupling the import graph cannot
see*](module.md#coupling-the-import-graph-cannot-see).** How they are driven:

| Property | Detail |
|---|---|
| Shared scope | both seam gates read their layer assignment from `tooling/architecture/_orm_layer_scope.py`, with a completeness test forcing every ORM module into a layer or an argued exemption |
| `pool_surface_check.py` ratchets three invariants | no unsanctioned `pool._private` from Layers 0–2; every referenced member exists on `Registry`; `components/` at zero — the runtime half of `orm-components-are-pure-python` |
| Width is reported, not ratcheted | on both seam gates. Layer 1 consulting `pool.field_inverses` is the design working; firing on a 10th public member would punish ordinary work |
| Two numbers, two meanings | the private counts in the module view are the *unsanctioned* ones the gate pins; a run's header prints the raw private width (6 and 4), including what `SANCTIONED_PRIVATE` blesses |
| `env_surface_check.py` also validates existence | which is what covers the four `env.__dict__["_field_cache_memo"]` string-key hot paths: ruff is blind, mypy sees only the 2 plain-attribute sites, and the `except KeyError` fallback would silently make the fast path permanently slow |
| `env_model_surface_check.py` pins a flat set | it answers "which models", never "who may reach them"; the full (package, model) cross-product would fire on every ordinary new reach |

A model-surface gate is only as wide as the syntaxes it reads. Until 2026-08-09
this one read `env[...]` and the accessor map; `registry[...]`/`pool[...]`,
`env.get("...")`, `"..." in registry` and a comodel in `Many2one("res.users",
…)` all named models it never saw, and two — `ir.demo_failure` and `res.partner`
— were absent from a set whose purpose is to be closed.

### The documentation gates

`subsystem_map_check.py` and `package_index_check.py` aim at the documentation
rather than the code. `doc_link_gate.py` proves a referenced file *exists*;
these prove a described package still *matches its directory*.

`package_index_check.py` covers four packages that document themselves
per-module: `odoo/db/README.md`'s *Module map*, `odoo/_monkeypatches/README.md`'s
*Patch Index*, `odoo/http/README.md`'s *Module map*, and
`odoo/upgrade_code/README.md`'s *Module map* (whose rows are dated script stems
such as `18.1-00-sql-constraint`, not importable identifiers).
`PACKAGE_INDEXES` is an inclusion list, so `test_every_core_readme_is_classified`
forces every core README into it or into `READMES_WITHOUT_AN_INDEX`.

The check is scoped to the inventory **section**. The READMEs carry other tables
that name `.py` files: `_monkeypatches`' *Recently Removed* table names eight
patches, six of which are modules that no longer exist (`urllib3`, `lxml`,
`xlrd`, `zeep`, `pytz`, `xlwt`); the other two retire a *patch* from a file that
is still there. An unscoped scan reports all six as failures against a document
that is exactly right — pinned by `test_section_scoping_is_load_bearing`, by
name rather than by count. A backticked path in this repo asserts the file
exists, so only *where on the page* a name sits distinguishes a citation from an
assertion.

### Checkers outside the thirty-two

Three more block without appearing in the table, enforced by the
`pytest tooling/architecture/` step rather than a `--check` invocation of their
own: `js_face_boundary.py` (a specifier stepping over a face),
`js_registry_layering.py`, and `model_member_surface_check.py`. Each carries a
real-tree test — `test_the_real_tree_holds_the_property_today`,
`test_the_surface_matches_the_committed_baseline` — so a violation fails the
self-test step, which is blocking.

`cross_repo_coherence.py` is a thirty-third checker and the only one outside CI: it
runs at the `pre-push` stage via `.pre-commit-config.yaml`, because GitHub
checks out this repo alone and the check needs the sibling checkouts. Opt-in per
clone — `pre-commit install --hook-type pre-push`.

`js_imports.py` is neither: no `main()`, no flags. It is the JS tokenizer nine of
the gates parse with — the easiest thing in the directory to mistake for a gate,
since it sits beside them and has a `test_js_imports.py`.

**Twenty-nine** is how many checkers CI runs as their own step; the self-test is
the step above them.

`model_member_surface_check.py` is the companion to `env_model_surface_check.py`:
*which members* the core calls on addon-owned models, against the `Protocol`s in
`orm/_protocols.py`.

Enumerations are gated only when derived. `tooling/test_repo_root.py`'s
`ROOT_ATTRS` was three short — `doc_symbol_gate`, `js_deployment_layers` and
`js_extension_surface` all resolve a checkout root and were asserted by nothing.
A hand-maintained roster is complete by assumption and says so in the voice it
would use if it were complete in fact. `subsystem_map_check.py` is the pattern
done right: it derives the tree and compares.

## The two count ratchets beyond the boundary gates

**Drift-zero count ratchet** (`tooling/ratchet/`, ADR-0006) — turns fourteen tool
counts into one-way contracts: **mypy, ruff, c901, c901_addons, eslint, tsc, jsfunclen, jsfunclen_mail, pyfunclen, jsprivate, jsserviceshape, jsserviceshape_mail, jsforcedrender and naming**
(floors in `tooling/ratchet/baselines/`, one JSON per gate). CI fails
on any increase and — in the default `exact` mode — on an un-committed decrease,
so every cleanup is locked in.

```bash
python tooling/ratchet/test_ratchet.py     # self-test the tool
python tooling/ratchet/ratchet.py --list   # current floors
```

### Measure a floor on a clean worktree, never on this checkout

**A floor is a claim about HEAD.** This workspace is shared by several sessions,
so the working directory carries changes that are in no commit, and a floor
harvested from it records a number no CI run can reproduce. Because the ratchets
run in `exact` mode, that fails the build in *both* directions — an unrecorded
improvement is as red as a regression.

```bash
git worktree add --detach /tmp/clean HEAD
cd /tmp/clean && python tooling/architecture/py_function_length.py --count
```

One measurement, 2026-08-09, both halves taken at the same instant — quoted as
history, not as the current floor, which moves whenever anyone shortens a
function:

| Where | `pyfunclen` that day | |
|---|---:|---|
| clean worktree at HEAD | 4750 | the committed floor at the time |
| this shared checkout | 4700 | 50 lower, from other sessions' uncommitted removals |

Flooring at 4700 would have pinned a number that reproduces nowhere. **The gap
is not a constant** — it is whatever happens to be uncommitted at that moment,
which is why the rule is "measure on a clean tree" and never "subtract the usual
difference". Read today's floor off `ratchet.py --list`; this table is an
illustration of the method and is not maintained against it.

This applies to **every** floor, and it has been rediscovered per-gate rather
than stated once: `ruff.toml`'s header records a dirty tree mis-setting the
`ruff` floor **twice**, `mypy` carries the same recipe for a different reason
(CI installs mypy alone, so dependency stubs shift the count), and
`baselines/pyfunclen.json`'s note records the measurement above. Three
statements of one rule, in three places, none of them general — the shape this
document set exists to remove.

No assertion backs this section: it constrains a *procedure*, not a count, and
the honest gate would be re-measuring all twelve floors on a clean tree, which
costs minutes for `mypy`, `eslint` and `tsc`. Recorded here so the next re-floor
does not rediscover it.

Two floors are split rather than aggregated, for one reason: an exact-match
ratchet over one integer cannot distinguish a fix from a regression, so a shared
bucket lets one mask the other.

| Floor | Split off because |
|---|---|
| `c901` | cyclomatic complexity in `odoo/`, threshold `[lint.mccabe] max-complexity = 20`. In the `ruff` aggregate a complexity fix could be masked by an unrelated new finding. It gated nothing before: `ruff.toml` selected the `C90` family while ignoring `C901`, its only rule |
| `c901_addons` | the same gate over `addons/`, where the 618 bundled modules and most business logic live and complexity was unbounded. The two trees move by different hands |

**A third floor, `ruff_docstring`, existed and is retired.** It is the worked
example of why the split is worth making and of what to do when the question
behind one gets answered. The `ruff` floor was 759, of which **758 were D1xx
missing-docstring findings** — the measured consequence of `eff67f80316`, which
stripped docstrings from `odoo/` on purpose. Those 758 units were fungible
slack, because an exact-match ratchet over one integer cannot distinguish
"someone added a docstring" from "someone introduced a real lint defect": a
commit adding *N* docstrings bought room for *N* unrelated new findings and
still totalled 759, which is how one genuine finding (an unused `threading`
import in `odoo/service/model.py`) stayed invisible. Splitting it took `ruff` to
a hard zero.

That left the split floor with an open *direction* — driving it to zero meant
re-adding what a commit had deliberately removed — and the honest answer turned
out to be neither: pydocstyle is no longer selected in `ruff.toml` at all, so
the floor measured nothing. **A ratchet whose gate has been retired is inert,
not held**, and inert is indistinguishable from held by reading. The baseline is
deleted, and `test_ratchet_baselines_match_documented_gates` now derives the
expected set from the gates the workflows actually drive rather than from a list
beside it, so the next retirement fails instead of lingering.

**DB-backed integration gate** (`.github/workflows/integration_tests.yml`,
ADR-0007) — boots PostgreSQL 18 and runs four suites, **each against its own
database**:

| Suite | Database | Notes |
|---|---|---|
| `base` | `ci_smoke` | less the excluded `TestReportsRendering` and `TestIrModelFieldsTranslation` |
| `test_http` | `ci_http` | |
| `test_orm` | `ci_orm` | added 2026-08-08. **1,130 test methods** under its `tests/` directory — the addon written to test the ORM, and the largest thing that was outside the lane. Above all `test_domain_evaluator_parity.py`: the only check that a `Domain` means the same to `search()` (SQL) and `filtered_domain()` (the in-memory predicate), with a generative suite asserting the two evaluators agree *or both refuse*. No DB-free tier can see a SQL/predicate divergence |
| `mrp` | `ci_mrp` | the first suite here that is not a `test_*` addon. Recursive BoM explosion, backorder splitting, multi-level procurement and compute chains across four models make it the deepest ORM consumer among the bundled addons; installing it gives `stock`, `product`, `uom` and `resource` their first DB-backed exercise through a real consumer |

Adding `test_orm` paid for itself on the first run:
`TestBackendDifferential.test_divergence_ilike_unaccent` asserted PostgreSQL's
`ilike` folds `Café` onto `cafe` without checking the `unaccent` extension is
installed. Every developer database inherits it from `db_template`; CI's
`template0` does not. It now skips on `registry.has_unaccent`.

Adding `mrp` repaired a suite nobody ran: `3bcf5d144f9` deleted
`stock.move.availability` having found "no consumer anywhere in the workspace",
missed `addons/mrp/tests/test_order.py`, which asserts on it, and left that test
erroring — every assertion after the failing line unexecuted.

Still outside the lane, in the order worth taking: `test_read_group` (122 test
methods, the only coverage of the five `read_group/` units) and
`test_access_rights` (31, record rules and ACLs).

Method counts, not line counts. A suite's size is an argument about what the
lane is missing, and raw lines churn on every edit inside it without moving that
argument — `test_orm` lost 68 lines between two runs an hour apart while its
1,110 methods did not change.

### The limits of "enforced"

**The integration gate is the only lane that runs addon tests.** All thirty-two
boundary checkers are structural and DB-free: they read import graphs, call
graphs, reached-member sets and documents. A change can satisfy all thirty-two,
and Tier 1 and Tier 2, and still be wrong — renaming `OrmCore`'s slots
(`cache`/`engine` → `_cache`/`_engine`) broke two DB-backed addon tests in
2026-08 while every gate and both DB-free tiers stayed green. Read a green
boundary job as "the structure holds", never as "the framework works".

A suite outside the lane is a suite nobody runs. When you add a test addon, add
it to the lane — **with its own database.** The suites interfere: `test_http`
depends on `mail`, whose `res_partner_views.xml` inherits
`base.view_res_partner_filter` anchored on `<filter name="inactive">`, and
base's `test_hard_reset_from_file_still_works` overwrites that view with a
minimal `<search>`. The write re-validates the children, so `-i base` is 5/5
green while `-i base,test_http` raises `ValidationError`.

ADR-0009 records how these gates were wired shut (mainline `push:` triggers,
full façade scope, re-measured floors) after an audit found each one bypassable.

## Known boundary exceptions

**None that are debt.** Two pinned rules, both
`core-does-not-depend-on-addons`, both scoped to `odoo.service`:
`service/_threaded.py` and `service/_worker.py` call `IrCron._process_jobs` /
`IrJob._process_jobs`, `@staticmethod` entry points that open their own cursor
because they run *before* a registry exists for the database, so there is no
`env` to route through. Both imports are deferred to call time, and no override
of either exists anywhere in `odoo`/`enterprise`/`agromarin`. Pinned rather than
allow-listed so they stay visible in every report.

The eight original contracts remain clean at zero. The exceptions the checker's
first run surfaced have all been paid down:

| Was | Now |
|---|---|
| Asset pipeline (`esbuild`, `esm_bridges`, `esm_graph`, `esm_registry`) in `libs/` | relocated to `odoo/tools/assets/` (ADR-0004). `asset_log` remains in `libs/` and is genuinely dependency-free. `constants` was kept beside it on the same reasoning and should not have been — it held 24 import-map asset paths (two into the optional `spreadsheet` and `survey` addons), the ORM prefetch and vacuum limits, and the `ir.cron`/`ir.job` NOTIFY channel names, with every consumer in `tools/`, `orm/`, `addons/base` or an addon tree. `libs-is-dependency-free` was green throughout, because a string literal produces no import edge. Split 2026-08-09 into `tools/assets/constants.py`, `orm/primitives.py` and `tools/constants.py`; the import-map builder moved to `tools/assets/import_map.py` |
| `libs/filesystem/osutil.py` imported `odoo.release` | the Windows service name is passed in by the caller (ADR-0004) |
| Layer-1 → Layer-2 deferred `BaseModel` imports in `orm/domain/ast.py` and `orm/fields/relational/` (since split into `_base`, `many2one`, `one2many`, `many2many`) | replaced by the `orm/_recordset.py` injection seam; what remains is `if TYPE_CHECKING:`-guarded annotation, which never executes (ADR-0001) |
| `MODULE_UNINSTALL_FLAG` in `addons/base/models/ir_model_common` | moved to `orm/primitives` (the ORM's `unlink` branches on it), re-exported from the addon for the `ir_model*` / `ir_module` code that sets it |
| `format_number`, `intersperse`, `split`, `parse_grouping` in `addons/base/models/res_lang`, reached twice from `tools/formatting.py` | moved to `libs/locale/number_format`; locale data arrives through a `LocaleConventions` **Protocol**, so `libs/` stays dependency-free while the addon's `LangData` satisfies it structurally |
