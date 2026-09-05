# The gates — what is mechanically enforced, and what that is worth

> Referenced by [`ARCHITECTURE.md`](ARCHITECTURE.md). The architecture is in
> [`module.md`](module.md) and [`runtime.md`](runtime.md); this file is the
> operator's manual for the machinery that keeps them true.

## Running the checks

The blocking checkers do **not** share one CLI, and a loop that assumes they
do fails on the count ratchets.

**Contract gates** take bare for a human-readable report, `--check` for a
blocking run (exit 1 on a new violation), `--json` for a machine-readable one:

```bash
python tooling/architecture/layer_check.py           # human-readable report
python tooling/architecture/layer_check.py --check   # exit 1 on new violations
python tooling/architecture/layer_check.py --json    # machine-readable
```

**Count ratchets** — `js_function_length`, `py_function_length`, `py_class_length`, `py_hook_arity`,
`py_x2many_count`, `werkzeug_in_addons`, `config_in_addons`, `sql_in_placeholder`, `py_count_as_boolean`,
`py_shadowed_member`, `naming_vocabulary`, `naming_core_vocabulary`,
`field_hook_naming`, `field_hook_purity`, `js_service_shape`,
`js_vacuous_assertions`, `js_duplication`, `compute_context_deps`,
`js_eager_mock_fixture`, `py_unresolved_calls`, `order_line_qty` and `bridge_budget` — implement no
`--check` at all. They print a number under `--count` and hand it
to `tooling/ratchet/ratchet.py`, which owns the floor. `js_private_access`,
`js_forced_render`, `js_ts_check` and `translation_catalog` also implement `--check`, but
are driven as ratchets, so they belong to this group. Run any of them bare
and it reports without enforcing.

**A figure stated twice is a figure pinned once.** Every count on these pages is
re-derived, but an `assertIn` is satisfied by the first copy and silent about
the second: this page said `forty-nine` in three places, and the risk register
said `32` in a row whose own entry body said 58, all four surviving a green gate
for weeks. The exclusion
(`test_no_page_states_a_suite_size_the_tree_does_not_hold`) reads every phrasing
across all nine pages, in digits or in words.

Reproduce the whole set. Self-test first, blocking, because a checker whose own
logic is broken reports green over code it never read; then both groups:

```bash
python -m pytest tooling/architecture/ -q

for gate in layer_check mixin_coupling_check subsystem_map_check \
            package_index_check env_surface_check pool_surface_check \
            env_model_surface_check worker_thread_surface_check \
            libs_facade_check facade_surface_check \
            mail_hook_keyword_check py_cycle_check \
            py_docstring_at_runtime \
            js_layer_check js_cycle_check \
            js_deployment_layers named_export_coherence js_suite_parity \
            js_context_narrowing \
            js_layer_cohesion js_import_resolution js_self_bridge \
            js_component_face js_component_data_access js_shadow_root \
            js_patch_blind_facade js_public_surface js_extension_surface \
            js_env_config_surface js_arch_info_surface js_field_record_surface \
            js_action_surface js_template_binding \
            xml_reference_coherence js_mixin_coupling edi_vocabulary \
            payment_vocabulary exchange_vocabulary credential_storage \
            py_addon_imports model_name_ownership \
            sql_placeholder module_depends_installable \
            external_dependency_pins; do
    python "tooling/architecture/$gate.py" --check || echo "FAILED: $gate"
done

while read -r gate floor; do
    python "tooling/architecture/$gate.py" --count \
        | xargs python tooling/ratchet/ratchet.py "$floor" --count \
        || echo "FAILED: $gate"
done <<'EOF'
js_function_length jsfunclen
py_function_length pyfunclen
py_class_length    pyclasslen
werkzeug_in_addons werkzeug_in_addons
config_in_addons   config_in_addons
py_x2many_count    py_x2many_count
sql_in_placeholder sql_in_placeholder
py_count_as_boolean py_count_as_boolean
py_hook_arity      py_hook_arity
py_shadowed_member py_shadowed_member
bridge_budget      bridge_budget
naming_vocabulary  naming
order_line_qty     orderlineqty
compute_context_deps computectx
field_hook_naming  fieldhooks
field_hook_purity  hookpurity
js_private_access  jsprivate
js_service_shape   jsserviceshape
js_forced_render   jsforcedrender
js_vacuous_assertions jsvacuous
js_eager_mock_fixture jseagerfixture
js_ts_check        jstscheck
js_duplication     jsduplication
translation_catalog translations
py_unresolved_calls unresolved_calls
naming_core_vocabulary naming_core
orphan_depends     orphandepends
EOF

# The two loops above run each checker once, at its default scope. A gate
# governing several scopes runs once per scope, and these are the other rows:
# the gate's argv left of the pipe and the ratchet's right of it, because a
# scope is not always spelled `--addon` and the flag is not always `--count`.
# `js_private_access` counts a second tree with `--count-cross-tree`, and
# `pyfunclen_addons` is the one floor driven `--mode no-increase`.
while IFS='|' read -r gate floor; do
    if [ -z "$floor" ]; then
        python tooling/architecture/$gate || echo "FAILED: $gate"
    else
        python tooling/architecture/$gate \
            | xargs python tooling/ratchet/ratchet.py $floor \
            || echo "FAILED: $gate"
    fi
done <<'EOF'
js_function_length.py --addon account --count|jsfunclen_account --count
js_function_length.py --addon mail --count|jsfunclen_mail --count
js_function_length.py --addon product --count|jsfunclen_product --count
js_function_length.py --addon stock --count|jsfunclen_stock --count
js_function_length.py --addon survey --count|jsfunclen_survey --count
js_private_access.py --count-cross-tree|jsprivate_crosstree --count
js_public_surface.py --addon mail --check|
js_service_shape.py --addon account --count|jsserviceshape_account --count
js_service_shape.py --addon mail --count|jsserviceshape_mail --count
js_service_shape.py --addon stock --count|jsserviceshape_stock --count
py_count_as_boolean.py --addon addons --count|py_count_as_boolean_addons --count
py_count_as_boolean.py --addon tests --count|py_count_as_boolean_tests --count
py_hook_arity.py --addon addons --count|py_hook_arity_addons --count
py_hook_arity.py --addon tests --count|py_hook_arity_tests --count
py_function_length.py --addon crm --count|pyfunclen_crm --count
py_function_length.py --addon loyalty --count|pyfunclen_loyalty --count
py_function_length.py --addon mail --count|pyfunclen_mail --count
py_function_length.py --addon survey --count|pyfunclen_survey --count
py_function_length.py --addon tests --count|pyfunclen_tests --count
py_function_length.py --addon tooling --count|pyfunclen_tooling --count
py_function_length.py --addon addons --count|pyfunclen_addons --mode no-increase --count
py_class_length.py --addon addons --count|pyclasslen_addons --mode no-increase --count
py_shadowed_member.py --addon addons --count|py_shadowed_member_addons --count
py_x2many_count.py --addon account --count|py_x2many_count_account --count
py_x2many_count.py --addon addons --count|py_x2many_count_addons --count
py_x2many_count.py --addon mail --count|py_x2many_count_mail --count
py_x2many_count.py --addon project --count|py_x2many_count_project --count
py_x2many_count.py --addon stock --count|py_x2many_count_stock --count
py_x2many_count.py --addon tests --count|py_x2many_count_tests --count
sql_in_placeholder.py --addon addons --count|sql_in_placeholder_addons --count
sql_in_placeholder.py --addon tests --count|sql_in_placeholder_tests --count
EOF
```

**A run from an assembled workspace judges more than a run from this repository
alone.** `js_public_surface`, `js_extension_surface` and
`xml_reference_coherence` are scope-aware: they judge every consumer checkout
they can see. From this repo alone that is the `odoo` scope only, while the same
command in an assembled workspace also judges `enterprise`, `design-themes` and
`agromarin` — and can fail on a finding belonging to a sibling repo. Read the
`scope '<name>'` prefix on a `[FAIL]` before concluding this tree is broken.

## Quality gates beyond the boundaries

The Python boundary checker is one gate among several. `pytest
tooling/architecture/` self-tests them; each then runs as a blocking step of its
own:

| Gate | What it locks |
|------|---------------|
| `layer_check.py` | the Python layering contracts in [`module.md`](module.md#enforced-dependency-rules) |
| `model_name_ownership.py` | one model name, one owning module, across every checkout at once. Two modules declaring the same bare `_name` is a silent **replace**, not a collision: the module the graph loads last wins the registry, the others lose their fields and methods, PostgreSQL keeps the loser's column as an orphan and retypes any column the two shared, and the install exits 0 with a warning. The question is relational, so it takes no `--addon` — the community `approval` against the enterprise `approvals*` family reads clean in either scope alone |
| `mixin_coupling_check.py` | the `self`-call graph the import graph cannot see |
| `js_mixin_coupling.py` | the same for JS: the `this`-call graph across `SearchModel`'s mixin chain, which produces no import edge and no cross-module member access, so every other JS gate reads it as empty |
| `env_surface_check.py` | the Layer→runtime `env` seam, that every reached `Environment` member exists, and Layer 1's whole view of the cache: the exact count of its `env._core` reaches and the exact set of `OrmCore` members they name |
| `pool_surface_check.py` | the Layer→runtime `pool` seam: private reach, member validity, and `components/` at zero |
| `env_model_surface_check.py` | the framework's string-keyed dependency on addon-owned models (`env["res.users"]`), which `core-does-not-depend-on-addons` cannot see — *which* models (exact set) **and** which subtrees may reach none. Reads six syntaxes, not just the subscript |
| `worker_thread_surface_check.py` | inline `threading.current_thread().<attr>` reads of per-request bookkeeping (`dbname`, `cursor_mode`, …), which mypy and `layer_check` cannot see |
| `libs_facade_check.py` | addon code **and every core package** importing `odoo.libs` **areas**, never their leaf modules |
| `facade_surface_check.py` | every name imported from a façade module against what that module actually exposes — `odoo.tools.misc` forwards names living in `odoo.libs`, so `__all__` states one surface and the module another, and an import of a name in neither fails at *module import time*: at install, in one addon, for whoever installs it next |
| `mail_hook_keyword_check.py` | the keywords `mail` passes to its own `_notify_*` / `_message_*` / `_track_*` / `_mail_*` hooks, against every override of them — `mail` is a framework whose extension points are implemented in dozens of addons across four repos, so its own **640**-test suite is structurally unable to see a signature it just broke, and `28ed9db3341` broke six overrides and merged green |
| `external_dependency_pins.py` | every `external_dependencies["python"]` a manifest declares against the requirements file of the repo that owns it — the two halves are written by hand in different files and nothing compared them, so three modules carried one without the other and could not install wherever the package was not dragged in by something else. A sibling may lean on this repo's `requirements.txt`, which every server process imports, but not on `requirements-addons.txt`, which the install command each sibling's own header documents does not read |
| `py_cycle_check.py` | Python import cycles in the core — the direction gates cannot see them |
| `py_docstring_at_runtime.py` | runtime code that reads `__doc__` where a `None` would raise — prose is stripped from `odoo/`, `tests/` and `tooling/` by policy, so `upgrade_code` could not print `--help` and `base_sparse_field` could not be imported |
| `subsystem_map_check.py` | the **subsystem map** in the module view against the actual tree |
| `package_index_check.py` | a package README's module index against the package |
| `js_layer_check.py` | the web addon's Feature-Sliced JS layers |
| `js_deployment_layers.py` | a *different* layering, in a different set of addons: `mail` files its client code by **where it runs** (`core/common/`, `discuss/core/public/`), the path segment deciding which asset bundles it lands in — so `common/` must never import from a higher layer |
| `js_cycle_check.py` | ESM import cycles across **every** addon's client source |
| `named_export_coherence.py` | `import { x }` with no matching `export` |
| `js_suite_parity.py` | the web addon's test tree against its source tree — a moved test must move with what it tests |
| `js_context_narrowing.py` | a `Pick<>` over a context bag against what its file reaches — over-declaring is invisible to tsc |
| `js_layer_cohesion.py` | each file filed with what it serves, not with what it resembles |
| `js_import_resolution.py` | every first-party specifier naming a real file |
| `js_self_bridge.py` | no source module resolving itself through the loader |
| `js_shadow_root.py` | every shadow root attached through `attachShadowRoot`, so its host carries the mark that makes it findable by a selector — there is no `:has-shadow-root` and no event on attach, and a root-crossing helper steps over an unmarked tree in silence |
| `js_component_face.py` | which directories under `components/` must HAVE a face — `js_face_boundary` refuses an import that reaches *past* one but a face is discovered rather than declared, so nothing said when a directory needs one |
| `js_component_data_access.py` | no component acquiring data at runtime — `components-below-entity` argues components take their data as props and enforces it by forbidding one import prefix no component uses |
| `js_forced_render.py` | web core not sweeping a subtree with `render(true)` — a forced render hides reads that subscribe to nothing |
| `js_patch_blind_facade.py` | a service's own callers going through its facade |
| `js_function_length.py` | the web addon's JS function-length budget |
| `js_duplication.py` | the web addon's duplicated JS, as byte-exact runs of 9+ significant lines — the one property the other JS gates cannot see, because a copied block is structurally identical to a block that belongs where it is |
| `js_vacuous_assertions.py` | a zero-count HOOT assertion naming a class no non-test file declares — the one assertion shape a wrong selector cannot be told from a passing test |
| `js_eager_mock_fixture.py` | a mock fixture mutating another addon's model at module scope — hoot imports every test file during collection and model definitions are job-scoped per test, so such a statement runs for every suite in the bundle EXCEPT the one that wrote it. Fifty of these cost 37 scoped failures across twelve POS addons; a hard zero with no baseline file |
| `js_ts_check.py` | how much client source is actually type-checked, as the count of `static/src` files carrying no leading `// @ts-check`. `tsconfig.json` sets `allowJs` with `strict`, `noImplicitAny` and `strictNullChecks` all false, so the directive is the only thing that decides whether a file's JSDoc is enforced — and a file without it reports zero errors to the `tsc` aggregate whether it is clean or wrong, which is why that floor cannot see this boundary move in either direction. The ignore list is read out of `eslint.config.mjs` rather than restated |
| `py_function_length.py` | the core's Python function-length budget — ratchets *excess lines* over 90, not the offender count, because splitting one long function raises the count while lowering the excess |
| `py_class_length.py` | the class-length budget, the mass a function budget cannot see — a class of short methods; ratchets *excess lines* over 400 per class summed over offenders, the unit `py_function_length.py` uses and for the same reason, in the same scopes (`pyclasslen` for the core, `pyclasslen_addons` for the bundled tree as one number, `--mode no-increase`) |
| `werkzeug_in_addons.py` | a non-test addon file importing werkzeug instead of the vocabulary `odoo.http` exports — the request, the response, `@route` and the HTTP exceptions a controller raises. 129 files did at the commit before the exceptions were re-exported, restating the framework's one WSGI-toolkit dependency in every module that serves a page. Ratchets the file count, because a file is written in one vocabulary or the other; not a hard zero, because an `ir.http` override that builds converters and a routing map keeps `werkzeug.routing` legitimately |
| `config_in_addons.py` | a non-test addon file reaching for the process-global `odoo.tools.config` — a subscript, a `.get`, a `.filestore`, a bare `config` handed on — through any of its four import spellings. The core reads typed, frozen snapshots since 2026-09 (`PoolSettings`, `HttpSettings`, `ServerSettings`, each built once at boot), so the addons are the other half of the population, and every reach is a coupling no import gate sees because `odoo.tools` is the door addons may use. Ratchets the reference count, not the file count: nine reads in one file are nine couplings to remove, and the migration that lands is per read |
| `py_x2many_count.py` | a counter that counts by hand — `len(record.x_ids)` in a `_compute*`, or `search_count` inside a loop over `self` — which `fields.Count` replaces. Ratchets the offender count, not excess lines as `py_function_length` beside it does: there is nothing to split, each site is one declaration that was not written |
| `sql_in_placeholder.py` | an `IN %s` psycopg3 cannot execute — a query handed straight to `cr.execute`, where nothing expands the placeholder, or an `SQL()` given a list where the builder's tuple branch is what makes `IN` work at all. A hard zero on all four scopes, with no baseline file on any; a query assembled into a variable and executed elsewhere is out of its reach and is held by tests instead |
| `py_count_as_boolean.py` | a `search_count` whose answer is only a yes or a no — consumed by an `if`, a `not`, a `bool()` or a comparison against `0` — and which passes no `limit`, so it scans the whole table to decide whether the first row exists. O(rows) against O(1); the fix is one keyword. A count used inside a larger boolean expression is excluded, because the value escapes there |
| `py_hook_arity.py` | a method carrying `@api.depends`, `@api.depends_context`, `@api.constrains`, `@api.onchange` or `@api.ondelete` that declares a parameter beyond `self`. The ORM calls these with no arguments, so such a parameter is either a `TypeError` waiting for the hook to fire or a decorator a refactor left on a helper while splitting the real hook out from under it — that second shape is silent, and the compute simply stops re-running. Held at zero on every scope with no baseline file, because each measures zero: a contract, not debt. Reports the fatal and the default-masked cases apart, since only the first raises |
| `py_shadowed_member.py` | a second `def`, nested `class` or assignment of a name already bound in the same class body. Python keeps the last, so the earlier definition never runs and nothing in the file says so — the shape a parallel edit produces at opposite ends of a long class. `ruff`'s F811 does not see it: its default dummy-variable regex drops every leading-underscore name, and an Odoo model method is always one. `@overload` stubs and the undecorated implementation they precede are one definition, not a shadow |
| `bridge_budget.py` | an auto-installed bridge -- two or more triggers, so every parent is already in each closure the bridge appears in -- carrying fewer than 60 lines of Python outside its manifest, tests and migrations. Such a module is a directory, a manifest and a security file for the lines it holds; folded into the parent that already depends on the others it costs the graph nothing. Ratchets the bridge count over `odoo/addons` and `addons` as one number, and prints the list bare because a fold is a decision per module: a stub for a feature still landing, or a bridge that keeps an OPL-1 dependency out of an LGPL-3 parent, stays one |
| `py_unresolved_calls.py` | a call that resolves to nothing this checkout defines — a method renamed without its callers, or a caller written against a method that never existed. Five such defects landed in one day, each invisible to every other gate: the call is syntactically fine, imports nothing and reaches no boundary, so it is only found when the branch runs. Ratchets the offender count |

| `js_private_access.py` | the cross-module private-access budget (`_member` reached past a module) |
| `js_service_shape.py` | a service handing back an instance, not a literal |
| `js_public_surface.py` | the web addon's published JS surface, as a ratchet |
| `js_extension_surface.py` | the web addon's inheritance surface — the methods downstream subclasses override, as a ratchet |
| `js_arch_info_surface.py` | the `archInfo` keys the view compiler writes into *generated template source*, where they are strings until OWL compiles them and no type, linter or member gate can follow them; plus each view type's parser against what its own directory reads |
| `js_field_record_surface.py` | what field widgets reach through `props.record` — `standardFieldProps` hands all **85** members of a live `RelationalRecord` to **112** widgets in this checkout, and a prop read is neither an import nor a class member, so no other gate sees it. Both figures are this repository's, not the workspace's: the gate's block was pinned once at 155 widgets from an assembled workspace, and failed in the build and nowhere else |
| `js_env_config_surface.py` | the keys read out of `env.config`, web's ambient per-action bag — inherited through the component tree, so it is neither an import nor a class member and the two surface gates above are blind to it |
| `js_action_surface.py` | the members reached on the `ActionManager` instance behind `env.services.action` — handed out by name, so blind to the import and member gates for the same reason. It found the contract under-declaring by four members that consumers reached at 45 call sites |
| `js_template_binding.py` | the names an OWL template calls against the component that owns it — the rule that what the XML names some JavaScript must provide, on a fourth string edge. It found `EmbeddedActionsBar` binding a handler its class had lost, which took the client down on every click for 48 commits |
| `naming_vocabulary.py` | the §2.4 method-naming verb vocabulary |
| `field_hook_naming.py` | what a `compute=`, `search=`, `inverse=`, `default=` or `domain=` names — the field declaration carries the method's name, so the two sit inches apart and can disagree; plus the domain builders whose name does not lead with it |
| `field_hook_purity.py` | whether the method a field attribute names is a hook at all — **12** are also called from production code, down from the 342 the gate opened with, which makes a compute's dependency graph something its callers compensate for |
| `order_line_qty.py` | writes of `product_uom_qty` on a sale or purchase order line — the field swapped meaning with `product_qty` in this fork (Appendix A) and both names survived, so writing the readonly one does not raise: `create` discards the value and the line silently becomes quantity 1, `write` lands it in the column while `product_qty` keeps its old value |
| `edi_vocabulary.py` | module names carrying `edi`, default-deny against its allowlist — the word names fiscal clearance, partner interchange and document import alike, and the collision has already produced a refactor proposal that would have made fifteen modules depend on a queue they do not use |
| `payment_vocabulary.py` | model names carrying `payment`, default-deny against its allowlist, plus the `_description` strings of those models against each other — the word names a settlement, a provider transaction, a method, a channel, a due schedule and more alike, and `account.payment.method` and `account.payment.method.line` shipped the same description, so the capability and its journal binding were one word and one sentence in the UI |
| `py_addon_imports.py` | every `odoo.addons.<addon>` import a module makes at import time resolves to an addon some checked-out repository provides — the Python twin of `named_export_coherence.py`, and the half nothing asked: `agromarin/mcp_server` imported `odoo.addons.rpc.tools.preflight` when no published repository carried it, so the module could not be imported against the published fork, and each repository measured alone stayed green because each sees only its own tree |
| `sql_placeholder.py` | `IN %s`, which psycopg 3 binds as `IN $1` and Postgres refuses — moved out of `test_lint` so it can see the tooling half of the tree and every repo, not only installed addons |
| `translation_catalog.py` | every `_()` literal against the msgids its module's `.pot` actually carries — a reflowed string still renders, in English, for every reader who asked for another language, and nothing else in the tree can see it |
| `compute_context_deps.py` | computes resolving the acting user (`env.user`, `env.uid`, `_get_guest_from_context`) without declaring the context key that keys their cache — the ORM cannot see that a method read `env`, and a test transaction has one uid, so six `mail`/`sms` fields shipped it and `discuss.channel._broadcast` sent every member the first member's unread count |
| `xml_reference_coherence.py` | view-arch strings (`widget=`, `js_class=`, `t-call`) against the JS registries and templates |
| `module_depends_installable.py` | an installable module naming, in `depends`, a module marked `installable: False` — disabling a module is how a replacement holds against the next module update, and it strands every dependent silently: the graph drops them with one WARNING, leaves them in state `to install`, and `odoo-bin` exits 0, so no suite runs and nothing reddens. Indian GST reporting sat unreachable that way until a manifest was read by hand |
| `orphan_depends.py` | an `@api.depends` carried by a method no field wires as `compute=`, `inverse=` or `search=` — the list is inert, so the field declares no dependency and answers with whatever it computed first, and Python, ruff and the registry all accept it |
| `naming_core_vocabulary.py` | §2.4's verb vocabulary over *every* function in the core package. `naming_vocabulary.py` implements the scope as a class-membership test, so module-level functions and plain-class methods are the population it cannot see |
| `exchange_vocabulary.py` | one exchange lifecycle, not forty-seven: `state`-shaped Selection fields across the modules that talk to a counterparty |
| `credential_storage.py` | a third-party secret resting in a stored `Char`/`Text` field instead of the vault |

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
rather than the code. `doc_link_gate.py` proves a referenced file *exists* and
that a `#fragment` names a heading the target still carries — it resolved the
file alone until renaming one heading here left two cross-view links dead with
every gate green; these prove a described package still *matches its
directory*.

`test_architecture_doc.py` is the third and by far the largest: it reads all
nine pages as one document. It is a **facade over `doc_gate/`**, one module per
view, and the facade's re-exports are what `pytest` collects — so a `TestCase`
the facade does not name runs nowhere. `test_the_facade_reaches_every_case`
derives that list from the package instead of trusting it, and
`test_architecture_doc_is_not_vacuous.py` re-runs the whole suite against an
empty page, patching `DOC` on **every** module that binds one: each view module
binds its own reference at import, so patching the facade alone would leave the
rest reading the real pages and report the suite as vacuous-proof when it was
merely unpatched.

`package_index_check.py` covers three packages that document themselves
per-module: `odoo/db/README.md`'s *Module map*, `odoo/_monkeypatches/README.md`'s
*Patch Index* and `odoo/http/README.md`'s *Module map*.
`PACKAGE_INDEXES` is an inclusion list, so `test_every_core_readme_is_classified`
forces every core README into it or into `READMES_WITHOUT_AN_INDEX`.

The check is scoped to the inventory **section**. The READMEs carry other tables
that name `.py` files: `_monkeypatches`' *Recently Removed* table records every
retired patch and why. Some of its rows name a module that no longer exists;
others retire a *patch* from a file that is still there. An unscoped scan reports
the first kind as failures against a document that is exactly right, which is
what makes the scoping load-bearing — pinned by
`test_section_scoping_is_load_bearing` and
`test_the_removed_table_is_why_scoping_is_needed`, **as properties, not as a
count or a list of names**. Both were pinned by name and count once, and both
then failed on the commits that did the right thing: retiring a patch is exactly
when a row is added. A restated number is a second copy that drifts, and a
retirement log is the last place to keep one. A backticked path in this repo
asserts the file exists, so only *where on the page* a name sits distinguishes a
citation from an assertion.

### Checkers enforced through the self-test

Five more block without appearing in the table, enforced by the
`pytest tooling/architecture/` step rather than a `--check` invocation of their
own: `js_face_boundary.py` (a specifier stepping over a face),
`js_registry_layering.py`, `model_member_surface_check.py`,
`format_literals.py`, and
`doc_restated_counts.py` (every prose figure against the tree that
produces it). Each carries a real-tree test —
`test_the_real_tree_holds_the_property_today`,
`test_the_surface_matches_the_committed_baseline`, and for the last one
`test_every_prose_figure_is_fresh` — so a violation fails the self-test step,
which is blocking. The membership of this list is derived rather
than kept: `GATES` in
`test_every_gate_refuses_an_empty_tree.py` is the roster, and these pages are
checked against it, so a gate can be in neither list only by being in no
list at all.

`doc_restated_counts.py` was outside this paragraph for as long as it existed,
which is the failure the paragraph describes: the roster in
`test_every_gate_refuses_an_empty_tree.py` already named it, `coding_guidelines.rst`
already called it a gate, and this page — the operator's manual for exactly this
machinery — said three.

`cross_repo_coherence.py` runs at the `pre-push` stage via
`.pre-commit-config.yaml`, because a run from this repository alone cannot see
the sibling checkouts the check needs. Opt-in per clone —
`pre-commit install --hook-type pre-push`.

`js_imports.py` is neither: no `main()`, no flags. It is the JS tokenizer the
checkers parse with — the easiest thing in the directory to mistake for a gate,
since it sits beside them and has a `test_js_imports.py`.

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

**Drift-zero count ratchet** (`tooling/ratchet/`) — turns seventy-eight tool
counts into one-way contracts: **mypy, ruff, c901, c901_addons, tsc, tsc_serviceworker, jsfunclen, jsfunclen_mail, jsfunclen_account, jsfunclen_survey, pyfunclen, pyfunclen_addons, pyclasslen, pyclasslen_addons, werkzeug_in_addons, config_in_addons, pyfunclen_mail, pyfunclen_crm, pyfunclen_survey, pyfunclen_tooling, py_x2many_count, py_x2many_count_addons, py_x2many_count_account, py_x2many_count_enterprise, py_x2many_count_agromarin, py_shadowed_member_addons, bridge_budget, jsprivate, jsprivate_crosstree, jsserviceshape, jsserviceshape_mail, jsforcedrender, jsvacuous, jstscheck, jsduplication, prettier_scss, naming, naming_enterprise, naming_agromarin, fieldhooks, hookpurity, computectx, translations, mypy_tools, service_types_untyped, orderlineqty, orderlineqty_enterprise, unresolved_calls, unresolved_calls_enterprise, unresolved_calls_agromarin, bundle_double_eval, lint_docstring, lint_gettext_developer_error, lint_gettext_placeholders, lint_gettext_repr, lint_gettext_variable, lint_missing_gettext, lint_n_plus_one_query, lint_noqa_rationale, lint_raise_unlink_override, lint_sql_injection, lint_gettext_developer_error_enterprise, lint_missing_gettext_enterprise, lint_n_plus_one_query_enterprise, lint_noqa_rationale_enterprise, lint_raise_unlink_override_enterprise, lint_sql_injection_enterprise, lint_gettext_developer_error_agromarin, lint_gettext_placeholders_agromarin, lint_gettext_repr_agromarin, lint_gettext_variable_agromarin, lint_missing_gettext_agromarin, lint_n_plus_one_query_agromarin, lint_noqa_rationale_agromarin, lint_sql_injection_agromarin, lint_noqa_rationale_design-themes, lint_record_reference and orphandepends**
(floors in `tooling/ratchet/baselines/`, one JSON per gate). `ratchet.py` fails
on any increase and — in the default `exact` mode — on an un-committed decrease,
so every cleanup is locked in.

**A gate with no baseline file is a hard zero, not an unset floor.**
`ratchet.py <gate> --count N` with no `baselines/<gate>.json` passes at 0 and
fails on anything above it, in either mode, naming the file it did not find;
`--update` is what opens a floor, and `--list` reads only the files, so it stays
a list of debt rather than of every contract. Many of the counts handed to
`ratchet.py` are held that way. Each was born at zero, so a file for it would
record no debt and no move — a contract wearing ratchet JSON, and `--list`
would report it as a floor to drive down. `assert_ratchet` under `test_lint`
has read an absent baseline as zero since it landed; this is the same rule for
the script-driven half, and the list of floors above derives from the baselines
directory (`test_ratchet_baselines_match_documented_gates`), so a file deleted
or added fails the page.

`pyfunclen_addons` and `pyclasslen_addons` are the two floors invoked `--mode
no-increase`, and the only ones whose scope is the bundled-addons tree entire. It exists because
`pyfunclen` stops at the core package: a long function *moved* out of `odoo/`
into an addon improved one reading and was measured by nothing on the other
side. The tree is too wide to hold still — it swung ~1700 excess lines in each
direction over a month — so the floor gives up locking improvements in order to
keep the property that matters, which is that excess cannot cross the boundary
unseen. `coding_guidelines.rst` *The ratchets* carries the argument.

```bash
python tooling/ratchet/test_ratchet.py     # self-test the tool
python tooling/ratchet/ratchet.py --list   # current floors
```

### Measure a floor on a clean worktree, never on this checkout

**A floor is a claim about HEAD.** This workspace is shared by several sessions,
so the working directory carries changes that are in no commit, and a floor
harvested from it records a number no clean-tree run can reproduce. Because the ratchets
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
(measured with mypy alone installed, so dependency stubs shift the count), and
`baselines/pyfunclen.json`'s note records the measurement above. Three
statements of one rule, in three places, none of them general — the shape this
document set exists to remove.

No assertion backs this section: it constrains a *procedure*, not a count, and
the honest gate would be re-measuring every floor on a clean tree,
which
costs minutes for `mypy` and `tsc`. Recorded here so the next re-floor
does not rediscover it.

Two floors are split rather than aggregated, for one reason: an exact-match
ratchet over one integer cannot distinguish a fix from a regression, so a shared
bucket lets one mask the other.

| Floor | Split off because |
|---|---|
| `c901` | cyclomatic complexity in `odoo/`, threshold `[lint.mccabe] max-complexity = 20`. In the `ruff` aggregate a complexity fix could be masked by an unrelated new finding. It gated nothing before: `ruff.toml` selected the `C90` family while ignoring `C901`, its only rule |
| `c901_addons` | the same gate over `addons/`, where the 650 bundled modules and most business logic live and complexity was unbounded. The two trees move by different hands |

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
expected set from the baseline files on disk rather than from a list beside
it, so the next retirement fails instead of lingering.

**DB-backed integration suites** — run against PostgreSQL 18, **each against
its own database**:

```bash
python odoo-bin --addons-path=odoo/addons,addons -d <db> -i <module> \
    --test-enable --test-tags /<module> --stop-after-init
```

The suites run this way, and what each covers: `base` (less the excluded
`TestReportsRendering` and `TestIrModelFieldsTranslation`), `test_http`,
`test_orm`, `mrp`, `certificate`, `stock`, `rpc`, `crm`, `data_recycle`,
`mixin_report_sql` with `test_mixin_report_sql`, `test_read_group`,
`test_access_rights`, `hr_work_entry` with `hr_work_entry_holidays`,
`hr_holidays`, the three `document_extract` branches, `test_base_order`,
`approval` with `test_approval`, `api_ai`, `project_hr`, `exchange`,
`date_range`, `account_coa`, `test_performance_compare`, `mail`, `test_mail`,
`mail_group` and `speech`. `rpc`, `mail`, `test_mail`, `mail_group` and `speech`
run **with** the HTTP server, because their `HttpCase` classes are the only
end-to-end coverage of what they test and none is a tour; the rest run
`--no-http`.

`test_orm` — **1,226 test methods** under its `tests/` directory — is the addon
written to test the ORM. Above all `test_domain_evaluator_parity.py`: the only
check that a `Domain` means the same to `search()` (SQL) and `filtered_domain()`
(the in-memory predicate), with a generative suite asserting the two evaluators
agree *or both refuse*. No DB-free tier can see a SQL/predicate divergence.

Running `test_orm` paid for itself on the first run:
`TestBackendDifferential.test_divergence_ilike_unaccent` asserted PostgreSQL's
`ilike` folds `Café` onto `cafe` without checking the `unaccent` extension is
installed. Every developer database inherits it from `db_template`; a bare
`template0` does not. It now skips on `registry.has_unaccent`.

Running `mrp` repaired a suite nobody ran: `3bcf5d144f9` deleted
`stock.move.availability` having found "no consumer anywhere in the workspace",
missed `addons/mrp/tests/test_order.py`, which asserts on it, and left that test
erroring — every assertion after the failing line unexecuted.

`test_read_group` (123 test methods, the only coverage of the five
`read_group/` units) and `test_access_rights` (54, record rules and ACLs) were
both green before anyone ran them — 123 of 123 and 52 of 52 with one
environment skip — so neither is a repair; they are coverage that existed and
ran nowhere. **A suite outside the set is a suite nobody runs.**

Method counts, not line counts. A suite's size is an argument about what the
set is missing, and raw lines churn on every edit inside it without moving that
argument — `test_orm` lost 68 lines between two runs an hour apart while its method
count did not move — quoted as method, not as a size, because the size is
stated once above and a second copy of it drifts.

### The limits of "enforced"

**The integration suites are the only thing that runs addon tests in Python.**
The boundary checkers are structural and DB-free: they read import graphs,
call graphs, reached-member sets and documents. A change can satisfy every one
of them, and Tier 1 and Tier 2, and still be wrong — renaming `OrmCore`'s slots
(`cache`/`engine` → `_cache`/`_engine`) broke two DB-backed addon tests in
2026-08 while every gate and both DB-free tiers stayed green. Read a green
boundary run as "the structure holds", never as "the framework works".

**The JS suites run through `tooling/hoot`.** `WebSuite` and `MobileWebSuite` in
`addons/web/tests/test_js.py` are addon tests like any other, but an integration
run that is `--stop-after-init` and `--no-http` skips both classes at
`setUpClass` and reports them as skipped, never as a pass and never as a
failure. `tooling/hoot/hoot-shard` — the same plan `WebSuite` runs, read from
`test_js.py` rather than restated, one suite per page load — must run **under
both presets**, desktop and mobile, each against its own shard databases,
because the two presets select by tag and neither set is a superset of the
other. Gate each pass on its own passed-test **count** as well as on the
runner's exit code: a suite contributing zero tests under a preset is not an
error to the runner, so a plan that narrowed to nothing would otherwise read as
PASS. The cost of not doing so was not hypothetical: a `mobile`-tagged test in
`@web/ui/dialog_service` sat failing from the day it landed, invisible because
the desktop preset skips it by tag and nothing else ran it at all, and
`@hr/m2x_avatar_employee` failed 6 of 11 for as long as nothing ran it.

A suite outside the set is a suite nobody runs. When you add a test addon, run
it — **with its own database.** The suites interfere: `test_http`
depends on `mail`, whose `res_partner_views.xml` inherits
`base.view_res_partner_filter` anchored on `<filter name="inactive">`, and
base's `test_hard_reset_from_file_still_works` overwrites that view with a
minimal `<search>`. The write re-validates the children, so `-i base` is 5/5
green while `-i base,test_http` raises `ValidationError`.

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
| Asset pipeline (`esbuild`, `esm_bridges`, `esm_graph`, `esm_registry`) in `libs/` | relocated to `odoo/tools/assets/`, being Odoo-coupled. `asset_log` remains in `libs/` and is genuinely dependency-free. `constants` was kept beside it on the same reasoning and should not have been — it held 24 import-map asset paths (two into the optional `spreadsheet` and `survey` addons), the ORM prefetch and vacuum limits, and the `ir.cron`/`ir.job` NOTIFY channel names, with every consumer in `tools/`, `orm/`, `addons/base` or an addon tree. `libs-is-dependency-free` was green throughout, because a string literal produces no import edge. Split 2026-08-09 into `tools/assets/constants.py`, `orm/primitives.py` and `tools/constants.py`; the import-map builder moved to `tools/assets/import_map.py` |
| `libs/filesystem/osutil.py` imported `odoo.release` | the Windows service name is passed in by the caller |
| Layer-1 → Layer-2 deferred `BaseModel` imports in `orm/domain/ast.py` and `orm/fields/relational/` (since split into `_base`, `many2one`, `one2many`, `many2many`) | replaced by the `orm/_recordset.py` injection seam; what remains is `if TYPE_CHECKING:`-guarded annotation, which never executes |
| `MODULE_UNINSTALL_FLAG` in `addons/base/models/ir_model_common` | moved to `orm/primitives` (the ORM's `unlink` branches on it), re-exported from the addon for the `ir_model*` / `ir_module` code that sets it |
| `format_number`, `intersperse`, `split`, `parse_grouping` in `addons/base/models/res_lang`, reached twice from `tools/formatting.py` | moved to `libs/locale/number_format`; locale data arrives through a `LocaleConventions` **Protocol**, so `libs/` stays dependency-free while the addon's `LangData` satisfies it structurally |
