# The gates — what is mechanically enforced, and what that is worth

> Referenced by [`ARCHITECTURE.md`](ARCHITECTURE.md). The architecture is in
> [`module.md`](module.md) and [`runtime.md`](runtime.md); this file is the
> operator's manual for the machinery that keeps them true.

## Running the checks

The sixty-six blocking checkers do **not** share one CLI, and a loop that
assumes they do fails on eighteen of them.

**Forty-three are contract gates.** Each takes bare for a human-readable
report, `--check` for CI (exit 1 on a new violation), `--json` for a
machine-readable one:

```bash
python tooling/architecture/layer_check.py           # human-readable report
python tooling/architecture/layer_check.py --check   # CI mode: exit 1 on new violations
python tooling/architecture/layer_check.py --json    # machine-readable
```

**Twenty-three are count ratchets.** `js_function_length`, `py_function_length`, `py_hook_arity`,
`py_x2many_count`, `sql_in_placeholder`, `py_count_as_boolean`,
`py_shadowed_member`, `naming_vocabulary`, `naming_core_vocabulary`,
`field_hook_naming`, `field_hook_purity`, `js_service_shape`,
`js_vacuous_assertions`, `js_duplication`, `compute_context_deps`,
`js_eager_mock_fixture`, `py_unresolved_calls` and `order_line_qty` implement no
`--check` at all — the eighteen a `--check` loop breaks on. They print a number under `--count` and hand it
to `tooling/ratchet/ratchet.py`, which owns the floor. `js_private_access`,
`js_forced_render` and `translation_catalog` also implement `--check`, but CI
drives them as ratchets, so they belong to this group. Run any of the twenty-one bare
and it reports without enforcing.

Forty-three plus twenty-three is sixty-six. All three figures derive from the
workflow, by the assertion that divides its own list; so does the membership of
the loop below (`test_the_reproduce_loop_is_exactly_the_contract_gates`) and,
since a gate governing several scopes gets a CI step per scope, the scoped
block after it (`test_the_recipe_reproduces_every_scoped_step`) — an enumerated
list is a gate only when something independently derives the enumeration. The
scoped block carried two of eight scoped gates by hand until that assertion
existed, at two scopes each against twenty-four, so this recipe reproduced
fifty-eight of the workflow's eighty-two steps and said nothing about the rest.

**A figure stated twice is a figure pinned once.** Every count on these pages is
re-derived, but an `assertIn` is satisfied by the first copy and silent about
the second: this page said `forty-nine` in three places, and the risk register
said `32` in a row whose own entry body said 58, all four surviving a green gate
for weeks. The exclusions
(`test_no_page_states_a_checker_total_the_workflow_does_not_run`,
`test_no_page_states_a_suite_size_the_tree_does_not_hold`) read every phrasing
across all nine pages, in digits or in words.

Reproduce the whole job. Self-test first, blocking, because a checker whose own
logic is broken reports green over code it never read; then both groups in the
workflow's order:

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
            py_addon_imports \
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
py_x2many_count    py_x2many_count
sql_in_placeholder sql_in_placeholder
py_count_as_boolean py_count_as_boolean
py_hook_arity      py_hook_arity
py_shadowed_member py_shadowed_member
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
js_duplication     jsduplication
translation_catalog translations
py_unresolved_calls unresolved_calls
naming_core_vocabulary naming_core
orphan_depends     orphandepends
module_suite_lane  suite_lane
EOF

# The two loops above run each checker once, at its default scope: 66 of the
# workflow's 96 steps. A gate governing several scopes gets one step per scope,
# and these are the other 30. The rows are the workflow's own argv, left/right of
# the pipe, because a scope is not always spelled `--addon` and the flag is not
# always `--count`: `js_private_access` counts a second tree with
# `--count-cross-tree`, and `pyfunclen_addons` is the one floor driven
# `--mode no-increase`.
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
py_function_length.py --count --addon addons|pyfunclen_addons --mode no-increase --count
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

**A local run judges more than CI does.** `js_public_surface`,
`js_extension_surface` and `xml_reference_coherence` are scope-aware: they judge
every consumer checkout they can see. GitHub checks out this repo alone, so CI
judges the `odoo` scope only, while the same command in an assembled workspace
also judges `enterprise`, `design-themes` and `agromarin` — and can fail on a
finding belonging to a sibling repo's own workflow. Read the `scope '<name>'`
prefix on a `[FAIL]` before concluding this tree is broken.

## Quality gates beyond the boundaries

The Python boundary checker (ADR-0005) is one gate among several. The
`Architecture Boundaries` workflow runs **sixty-six** blocking checkers, after
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
| `facade_surface_check.py` | every name imported from a façade module against what that module actually exposes — `odoo.tools.misc` forwards names living in `odoo.libs`, so `__all__` states one surface and the module another, and an import of a name in neither fails at *module import time*: at install, in one addon, for whoever installs it next |
| `mail_hook_keyword_check.py` | the keywords `mail` passes to its own `_notify_*` / `_message_*` / `_track_*` / `_mail_*` hooks, against every override of them — `mail` is a framework whose extension points are implemented in dozens of addons across four repos, so its own **600**-test suite is structurally unable to see a signature it just broke, and `28ed9db3341` broke six overrides and merged green |
| `external_dependency_pins.py` | every `external_dependencies["python"]` a manifest declares against the requirements file of the repo that owns it — the two halves are written by hand in different files and nothing compared them, so three modules carried one without the other and could not install wherever the package was not dragged in by something else. A sibling may lean on this repo's `requirements.txt`, which every server process imports, but not on `requirements-addons.txt`, which the install command each sibling's own header documents does not read |
| `py_cycle_check.py` | Python import cycles in the core — the direction gates cannot see them |
| `py_docstring_at_runtime.py` | runtime code that reads `__doc__` where a `None` would raise — prose is stripped from `odoo/`, `tests/` and `tooling/` by policy, so `upgrade_code` could not print `--help` and `base_sparse_field` could not be imported (ADR-0076) |
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
| `js_shadow_root.py` | every shadow root attached through `attachShadowRoot`, so its host carries the mark that makes it findable by a selector — there is no `:has-shadow-root` and no event on attach, and a root-crossing helper steps over an unmarked tree in silence (ADR-0069) |
| `js_component_face.py` | which directories under `components/` must HAVE a face — `js_face_boundary` refuses an import that reaches *past* one but a face is discovered rather than declared, so nothing said when a directory needs one (ADR-0047) |
| `js_component_data_access.py` | no component acquiring data at runtime — `components-below-entity` argues components take their data as props and enforces it by forbidding one import prefix no component uses (ADR-0046) |
| `js_forced_render.py` | web core not sweeping a subtree with `render(true)` — a forced render hides reads that subscribe to nothing |
| `js_patch_blind_facade.py` | a service's own callers going through its facade |
| `js_function_length.py` | the web addon's JS function-length budget |
| `js_duplication.py` | the web addon's duplicated JS, as byte-exact runs of 9+ significant lines — the one property the other JS gates cannot see, because a copied block is structurally identical to a block that belongs where it is (ADR-0045) |
| `js_vacuous_assertions.py` | a zero-count HOOT assertion naming a class no non-test file declares — the one assertion shape a wrong selector cannot be told from a passing test |
| `js_eager_mock_fixture.py` | a mock fixture mutating another addon's model at module scope — hoot imports every test file during collection and model definitions are job-scoped per test, so such a statement runs for every suite in the bundle EXCEPT the one that wrote it (ADR-0067). Fifty of these cost 37 scoped failures across twelve POS addons; a hard zero with no baseline file |
| `py_function_length.py` | the core's Python function-length budget — ratchets *excess lines* over 90, not the offender count, because splitting one long function raises the count while lowering the excess |
| `py_x2many_count.py` | a counter that counts by hand — `len(record.x_ids)` in a `_compute*`, or `search_count` inside a loop over `self` — which ADR-0052 replaced with `fields.Count`. Ratchets the offender count, not excess lines as `py_function_length` beside it does: there is nothing to split, each site is one declaration that was not written |
| `sql_in_placeholder.py` | an `IN %s` psycopg3 cannot execute — a query handed straight to `cr.execute`, where nothing expands the placeholder, or an `SQL()` given a list where the builder's tuple branch is what makes `IN` work at all (ADR-0055). A hard zero on all four scopes, with no baseline file on any; a query assembled into a variable and executed elsewhere is out of its reach and is held by tests instead |
| `py_count_as_boolean.py` | a `search_count` whose answer is only a yes or a no — consumed by an `if`, a `not`, a `bool()` or a comparison against `0` — and which passes no `limit`, so it scans the whole table to decide whether the first row exists (ADR-0057). O(rows) against O(1); the fix is one keyword. A count used inside a larger boolean expression is excluded, because the value escapes there |
| `py_hook_arity.py` | a method carrying `@api.depends`, `@api.depends_context`, `@api.constrains`, `@api.onchange` or `@api.ondelete` that declares a parameter beyond `self` (ADR-0075). The ORM calls these with no arguments, so such a parameter is either a `TypeError` waiting for the hook to fire or a decorator a refactor left on a helper while splitting the real hook out from under it — that second shape is silent, and the compute simply stops re-running. Held at zero on every scope with no baseline file, because each measures zero: a contract, not debt. Reports the fatal and the default-masked cases apart, since only the first raises |
| `py_shadowed_member.py` | a second `def`, nested `class` or assignment of a name already bound in the same class body (ADR-0062). Python keeps the last, so the earlier definition never runs and nothing in the file says so — the shape a parallel edit produces at opposite ends of a long class. `ruff`'s F811 does not see it: its default dummy-variable regex drops every leading-underscore name, and an Odoo model method is always one. `@overload` stubs and the undecorated implementation they precede are one definition, not a shadow |
| `py_unresolved_calls.py` | a call that resolves to nothing this checkout defines — a method renamed without its callers, or a caller written against a method that never existed (ADR-0058). Five such defects landed in one day, each invisible to every other gate: the call is syntactically fine, imports nothing and reaches no boundary, so it is only found when the branch runs. Ratchets the offender count |

| `js_private_access.py` | the cross-module private-access budget (`_member` reached past a module) |
| `js_service_shape.py` | a service handing back an instance, not a literal |
| `js_public_surface.py` | the web addon's published JS surface, as a ratchet |
| `js_extension_surface.py` | the web addon's inheritance surface — the methods downstream subclasses override, as a ratchet |
| `js_arch_info_surface.py` | the `archInfo` keys the view compiler writes into *generated template source*, where they are strings until OWL compiles them and no type, linter or member gate can follow them; plus each view type's parser against what its own directory reads |
| `js_field_record_surface.py` | what field widgets reach through `props.record` — `standardFieldProps` hands all **85** members of a live `RelationalRecord` to **111** widgets in this checkout, and a prop read is neither an import nor a class member, so no other gate sees it. Both figures are this repository's, not the workspace's: the gate's block was pinned once at 155 widgets from an assembled workspace, and failed in the build and nowhere else |
| `js_env_config_surface.py` | the keys read out of `env.config`, web's ambient per-action bag — inherited through the component tree, so it is neither an import nor a class member and the two surface gates above are blind to it |
| `js_action_surface.py` | the members reached on the `ActionManager` instance behind `env.services.action` — handed out by name, so blind to the import and member gates for the same reason. It found the contract under-declaring by four members that consumers reached at 45 call sites |
| `js_template_binding.py` | the names an OWL template calls against the component that owns it — ADR-0032's rule on a fourth string edge. It found `EmbeddedActionsBar` binding a handler its class had lost, which took the client down on every click for 48 commits |
| `naming_vocabulary.py` | the §2.4 method-naming verb vocabulary |
| `field_hook_naming.py` | what a `compute=`, `search=`, `inverse=`, `default=` or `domain=` names — the field declaration carries the method's name, so the two sit inches apart and can disagree; plus the domain builders whose name does not lead with it (ADR-0049, ADR-0050, ADR-0054) |
| `field_hook_purity.py` | whether the method a field attribute names is a hook at all — **12** are also called from production code, down from the 342 ADR-0051 opened with, which makes a compute's dependency graph something its callers compensate for (ADR-0051) |
| `order_line_qty.py` | writes of `product_uom_qty` on a sale or purchase order line — the field swapped meaning with `product_qty` in this fork (Appendix A) and both names survived, so writing the readonly one does not raise: `create` discards the value and the line silently becomes quantity 1, `write` lands it in the column while `product_qty` keeps its old value |
| `edi_vocabulary.py` | module names carrying `edi`, default-deny against ADR-0048's allowlist — the word names fiscal clearance, partner interchange and document import alike, and the collision has already produced a refactor proposal that would have made fifteen modules depend on a queue they do not use |
| `payment_vocabulary.py` | model names carrying `payment`, default-deny against ADR-0070's allowlist, plus the `_description` strings of those models against each other — the word names a settlement, a provider transaction, a method, a channel, a due schedule and more alike, and `account.payment.method` and `account.payment.method.line` shipped the same description, so the capability and its journal binding were one word and one sentence in the UI |
| `py_addon_imports.py` | every `odoo.addons.<addon>` import a module makes at import time resolves to an addon some checked-out repository provides — the Python twin of `named_export_coherence.py`, and the half nothing asked: `agromarin/mcp_server` imported `odoo.addons.rpc.tools.preflight` when no published repository carried it, so the module could not be imported against the published fork, and both repositories' CI stayed green because each sees only its own tree |
| `sql_placeholder.py` | `IN %s`, which psycopg 3 binds as `IN $1` and Postgres refuses — moved out of `test_lint` so it can see the tooling half of the tree and every repo, not only installed addons |
| `translation_catalog.py` | every `_()` literal against the msgids its module's `.pot` actually carries — a reflowed string still renders, in English, for every reader who asked for another language, and nothing else in the tree can see it |
| `compute_context_deps.py` | computes resolving the acting user (`env.user`, `env.uid`, `_get_guest_from_context`) without declaring the context key that keys their cache — the ORM cannot see that a method read `env`, and a test transaction has one uid, so six `mail`/`sms` fields shipped it and `discuss.channel._broadcast` sent every member the first member's unread count |
| `xml_reference_coherence.py` | view-arch strings (`widget=`, `js_class=`, `t-call`) against the JS registries and templates |
| `module_depends_installable.py` | an installable module naming, in `depends`, a module marked `installable: False` — disabling a module is how a replacement holds against the next module update, and it strands every dependent silently: the graph drops them with one WARNING, leaves them in state `to install`, and `odoo-bin` exits 0, so no suite runs and no lane reddens (ADR-0064). Indian GST reporting sat unreachable that way until a manifest was read by hand |
| `orphan_depends.py` | an `@api.depends` carried by a method no field wires as `compute=`, `inverse=` or `search=` — the list is inert, so the field declares no dependency and answers with whatever it computed first, and Python, ruff and the registry all accept it (ADR-0085) |
| `naming_core_vocabulary.py` | §2.4's verb vocabulary over *every* function in the core package. `naming_vocabulary.py` implements the scope as a class-membership test, so module-level functions and plain-class methods are the population it cannot see |
| `module_suite_lane.py` | a module whose test suite no workflow lane names, so nothing ever runs it |
| `exchange_vocabulary.py` | one exchange lifecycle, not forty-seven: `state`-shaped Selection fields across the modules that talk to a counterparty (ADR-0080) |
| `credential_storage.py` | a third-party secret resting in a stored `Char`/`Text` field instead of the vault (ADR-0081) |

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

`package_index_check.py` covers four packages that document themselves
per-module: `odoo/db/README.md`'s *Module map*, `odoo/_monkeypatches/README.md`'s
*Patch Index*, `odoo/http/README.md`'s *Module map*, and
`odoo/upgrade_code/README.md`'s *Module map* (whose rows are dated script stems
such as `18.1-00-sql-constraint`, not importable identifiers).
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

### Checkers outside the sixty-six

Five more block without appearing in the table, enforced by the
`pytest tooling/architecture/` step rather than a `--check` invocation of their
own: `js_face_boundary.py` (a specifier stepping over a face),
`js_registry_layering.py`, `model_member_surface_check.py`,
`format_literals.py`, and
`doc_restated_counts.py` (ADR-0041 — every prose figure against the tree that
produces it). Each carries a real-tree test —
`test_the_real_tree_holds_the_property_today`,
`test_the_surface_matches_the_committed_baseline`, and for the last one
`test_every_prose_figure_is_fresh` — so a violation fails the self-test step,
which is blocking. **Sixty-six run as steps of their own and five block through
the self-test: seventy-one in all.** The membership of this list is derived rather
than kept: `GATES` in
`test_every_gate_refuses_an_empty_tree.py` is the roster, and it is compared
against the workflow's, so a gate can be in neither list only by being in no
list at all.

`doc_restated_counts.py` was outside this paragraph for as long as it existed,
which is the failure the paragraph describes: the roster in
`test_every_gate_refuses_an_empty_tree.py` already named it, `coding_guidelines.rst`
already called it a gate, and this page — the operator's manual for exactly this
machinery — said three.

`cross_repo_coherence.py` is a seventy-second checker and the only one outside CI: it
runs at the `pre-push` stage via `.pre-commit-config.yaml`, because GitHub
checks out this repo alone and the check needs the sibling checkouts. Opt-in per
clone — `pre-commit install --hook-type pre-push`.

`js_imports.py` is neither: no `main()`, no flags. It is the JS tokenizer
**eleven** of the checkers parse with — the easiest thing in the directory to
mistake for a gate, since it sits beside them and has a `test_js_imports.py`.
Eleven and not eight, which is what counting only the table above would give:
`js_face_boundary` and `js_registry_layering` are two of the three enforced by
the self-test rather than a step of their own, and `cross_repo_coherence` is the
third.

**Ninety-six** is how many steps CI runs the sixty-six in, each step invoking
exactly one checker; the self-test is the step above them all. The two figures
differ because a gate governing several scopes gets one step per scope —
`py_function_length` alone accounts for eight.

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

**Drift-zero count ratchet** (`tooling/ratchet/`, ADR-0006) — turns seventy-eight tool
counts into one-way contracts: **mypy, ruff, c901, c901_addons, eslint, tsc, tsc_serviceworker, jsfunclen, jsfunclen_mail, jsfunclen_account, jsfunclen_survey, pyfunclen, pyfunclen_addons, pyfunclen_mail, pyfunclen_crm, pyfunclen_survey, pyfunclen_tooling, py_x2many_count, py_x2many_count_addons, py_x2many_count_account, py_x2many_count_enterprise, py_x2many_count_agromarin, py_shadowed_member_addons, jsprivate, jsprivate_crosstree, jsserviceshape, jsserviceshape_mail, jsforcedrender, jsvacuous, jsduplication, prettier_scss, naming, naming_enterprise, naming_agromarin, fieldhooks, hookpurity, computectx, translations, mypy_tools, service_types_untyped, orderlineqty, orderlineqty_enterprise, unresolved_calls, unresolved_calls_enterprise, unresolved_calls_agromarin, bundle_double_eval, lint_docstring, lint_gettext_developer_error, lint_gettext_placeholders, lint_gettext_repr, lint_gettext_variable, lint_manifest_shape, lint_missing_gettext, lint_n_plus_one_query, lint_noqa_rationale, lint_raise_unlink_override, lint_sql_injection, lint_xml_attrib_order, lint_xml_field_order, lint_xml_unformatted, lint_gettext_developer_error_enterprise, lint_missing_gettext_enterprise, lint_n_plus_one_query_enterprise, lint_noqa_rationale_enterprise, lint_raise_unlink_override_enterprise, lint_sql_injection_enterprise, lint_gettext_developer_error_agromarin, lint_gettext_placeholders_agromarin, lint_gettext_repr_agromarin, lint_gettext_variable_agromarin, lint_missing_gettext_agromarin, lint_n_plus_one_query_agromarin, lint_noqa_rationale_agromarin, lint_sql_injection_agromarin, lint_noqa_rationale_design-themes, lint_record_reference, orphandepends and suite_lane**
(floors in `tooling/ratchet/baselines/`, one JSON per gate). CI fails
on any increase and — in the default `exact` mode — on an un-committed decrease,
so every cleanup is locked in.

**A gate with no baseline file is a hard zero, not an unset floor.**
`ratchet.py <gate> --count N` with no `baselines/<gate>.json` passes at 0 and
fails on anything above it, in either mode, naming the file it did not find;
`--update` is what opens a floor, and `--list` reads only the files, so it stays
a list of debt rather than of every contract. Thirty-six of the counts the
workflows hand to `ratchet.py` are held that way: **jsfunclen_stock, jsfunclen_product, pyfunclen_loyalty, pyfunclen_tests, py_x2many_count_mail, py_x2many_count_stock, py_x2many_count_project, sql_in_placeholder, sql_in_placeholder_addons, sql_in_placeholder_enterprise, sql_in_placeholder_agromarin, py_count_as_boolean, py_count_as_boolean_addons, py_count_as_boolean_enterprise, py_count_as_boolean_agromarin, py_hook_arity, py_hook_arity_addons, py_shadowed_member, py_shadowed_member_enterprise, py_shadowed_member_agromarin, py_shadowed_member_design-themes, jsserviceshape_account, jsserviceshape_stock, jseagerfixture, naming_design-themes, mypy_cli, mypy_tests, orderlineqty_agromarin, orderlineqty_design-themes, mypy_core_rest, mypy_upgrade_code, naming_core, py_count_as_boolean_tests, py_hook_arity_tests, py_x2many_count_tests and sql_in_placeholder_tests**.
Each was born at zero, so the file it once carried recorded no debt and no
move — a contract wearing ratchet JSON, and `--list` reported it as a floor to
drive down. `assert_ratchet` under `test_lint` has read an absent baseline as
zero since it landed; this is the same rule for the workflow-driven half, and
the enumeration above derives from the workflows
(`test_ratchet_baselines_match_documented_gates`), so a file deleted or a
step added fails the page rather than the lane.

`pyfunclen_addons` is the only floor invoked `--mode no-increase`, and it is the
only one whose scope is the bundled-addons tree entire. It exists because
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
the honest gate would be re-measuring all ninety-five floors on a clean tree,
which
costs minutes for `mypy`, `eslint` and `tsc`. Recorded here so the next re-floor
does not rediscover it.

Two floors are split rather than aggregated, for one reason: an exact-match
ratchet over one integer cannot distinguish a fix from a regression, so a shared
bucket lets one mask the other.

| Floor | Split off because |
|---|---|
| `c901` | cyclomatic complexity in `odoo/`, threshold `[lint.mccabe] max-complexity = 20`. In the `ruff` aggregate a complexity fix could be masked by an unrelated new finding. It gated nothing before: `ruff.toml` selected the `C90` family while ignoring `C901`, its only rule |
| `c901_addons` | the same gate over `addons/`, where the 639 bundled modules and most business logic live and complexity was unbounded. The two trees move by different hands |

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
ADR-0007) — boots PostgreSQL 18 and runs twenty-five suites, **each against its own
database**:

| Suite | Database | Notes |
|---|---|---|
| `base` | `ci_smoke` | less the excluded `TestReportsRendering` and `TestIrModelFieldsTranslation` |
| `test_http` | `ci_http` | |
| `test_orm` | `ci_orm` | added 2026-08-08. **1,214 test methods** under its `tests/` directory — the addon written to test the ORM, and the largest thing that was outside the lane. Above all `test_domain_evaluator_parity.py`: the only check that a `Domain` means the same to `search()` (SQL) and `filtered_domain()` (the in-memory predicate), with a generative suite asserting the two evaluators agree *or both refuse*. No DB-free tier can see a SQL/predicate divergence |
| `mrp` | `ci_mrp` | the first suite here that is not a `test_*` addon. Recursive BoM explosion, backorder splitting, multi-level procurement and compute chains across four models make it the deepest ORM consumer among the bundled addons; installing it gives `stock`, `product`, `uom` and `resource` their first DB-backed exercise through a real consumer |
| `certificate` | `ci_certificate` | added 2026-08-20. Owns X.509 parsing, private-key loading and the signing API for `l10n_mx_edi`, `l10n_cl_edi`, `sign`, `account_edi_proxy_client` and fifteen more consumers, and ran in no lane at all. What it catches is not an ordinary regression: a key that signs with the wrong digest breaks fiscal submission in whichever country is downstream, silently, until a tax authority refuses the file |
| `stock` | `ci_stock` | added 2026-08-22 — the same hole as `mrp`'s, one layer down: `mrp` installs stock and exercises it as a consumer but selects `/mrp`, so no workflow had ever run one of stock's own 1,819 tests. The 8 HttpCase tours are excluded rather than skipped silently, because `--no-http` would turn each into a success that never ran |
| `rpc` | `ci_rpc` | added 2026-08-27. The only suite here that runs **with** the HTTP server: its three `HttpCase` classes drive real XML-RPC and `/json/2` requests through `url_open` and `ServerProxy`, so `--no-http` would skip the 25 tests that are the only end-to-end coverage of the wire format. None is a tour and none needs a browser |
| `crm` | `ci_crm` | added 2026-08-28. Installed by exactly one workflow before this — `module_installability.yml`, which asks only whether the graph assembles and passes no `--test-enable` — so its whole suite and every one of its `assertQueryCount` pins were executed by nothing, which is how the pins came to sit well over the tree they measure. `-i crm` is the whole install set; the pins are set to the maximum of the three install shapes measured, so a community-only lane cannot pass a pin the enterprise shape would fail. The lane's own comment carries the counts |
| `data_recycle` | `ci_recycle` | added 2026-08-28. The module whose cron archives and deletes *other* modules' records, and which ran in no lane: its suite ran only by hand, which is how it shipped a queue that acted on records after their rule had stopped selecting them, a rule with no filter that emptied the whole table, and a cron that ended its night on the first record a foreign key protected. Its two tour tests need headless Chrome, so `--no-http` skips their class and reports it as skipped rather than as a pass |
| `mixin_report_sql` | `ci_sql_report` | added 2026-08-28, and the cheapest lane here — the module depends on `base` alone. Its 30 tests had been run by nothing at all: this lane named seven other suites, `module_installability.yml` enables only one `test_lint` class, and pytest collects none of it because the cases are `TransactionCase` while `testpaths` holds the DB-free tiers. The suite was patching the abstract mixins in place rather than building a real report, so five correctness defects sat behind that gap; rewritten against concrete fixture models it runs 78 |
| `test_read_group` | `ci_read_group` | added 2026-08-28. The only coverage of the five `read_group/` units — `_empty`, `fill`, `format`, `mixin`, `sql` — and reachable by neither DB-free tier by construction: a `read_group` is a `GROUP BY`, and what it groups is decided by SQL the in-memory path never runs |
| `test_access_rights` | `ci_access_rights` | added 2026-08-28. Record rules and ACLs, the one subsystem here where a wrong answer is a security answer rather than a broken one. One of its 52 skips for want of an HTTP server and is reported as skipped |
| `hr_work_entry`, `hr_work_entry_holidays` | `ci_hr_work_entry` | added 2026-08-30 — 71 tests that ran in no workflow. The pair installs together because both live in `odoo/addons`; the three enterprise bridges cannot be in this lane. Neither module has a tour, so the `--no-http` run is the whole suite |
| `hr_holidays` | `ci_hr_holidays` | added 2026-08-30, and run `--no-http`, so its tour classes are reported as skipped rather than as passes |
| `document_extract` account branch | `ci_docext_account` | installs `document_extract_account_purchase`, whose closure is `document_extract_account` and `document_extract`; runs all three tags. 149 tests measured 2026-09-01. Split from the six-module lane so no two independent suites share a database. Not the whole family — `document_extract_ai` lives in agromarin and `document_extract_account_bank_statement` in enterprise, neither visible to this checkout, while `document_extract_barcode` and `document_extract_ocr` declare external dependencies `requirements-addons.txt` does not carry |
| `document_extract` recruitment branch | `ci_docext_recruit` | installs `document_extract_hr_recruitment_skills`, whose closure is `document_extract_hr_recruitment`; 13 tests |
| `document_extract` expense branch | `ci_docext_expense` | installs `document_extract_hr_expense`; 9 tests |
| `test_base_order` | `ci_base_order` | one module: `sale` and `purchase` now arrive through `test_base_order`'s own `depends`, where they belong — without them the suite reports 67 errors, 55 of them `KeyError: 'order_lock_so'`, a scope artefact that reads exactly like a broken module. Runs `/test_base_order` and `/base_order` together because both are that one closure; 281 tests, 0 failed |
| `approval` | `ci_approval` | added 2026-08-28, and not a repair — it passes at 544 tests, one skipped for want of something the environment cannot provide. The scope is the module's own `addons/approval/machine_doc_v1/conventions.md`, which states `-i approval --test-tags '/approval'` |
| `api_ai` | `ci_api_ai` | 181 tests. Installing it installs `api_transport` and `credential`, whose own suites stay unrun by the decision in CLAUDE.md §9.6 — naming modules in `--test-tags` rather than counting what a lane installs is what holds that line |
| `project_hr` | `ci_project_hr` | 33 tests |
| `exchange` | `ci_exchange` | installs `exchange`, whose closure is `mixin_encryption`; runs both tags, 86 tests |
| `date_range` | `ci_date_range` | installs `test_date_range`, whose closure is `date_range`; runs both tags, 37 tests |
| `account_coa` | `ci_account_coa` | 30 tests |
| `test_performance_compare` | `ci_perf_compare` | 1 test, and it is the cheapest lane here |

Adding `test_orm` paid for itself on the first run:
`TestBackendDifferential.test_divergence_ilike_unaccent` asserted PostgreSQL's
`ilike` folds `Café` onto `cafe` without checking the `unaccent` extension is
installed. Every developer database inherits it from `db_template`; CI's
`template0` does not. It now skips on `registry.has_unaccent`.

Adding `mrp` repaired a suite nobody ran: `3bcf5d144f9` deleted
`stock.move.availability` having found "no consumer anywhere in the workspace",
missed `addons/mrp/tests/test_order.py`, which asserts on it, and left that test
erroring — every assertion after the failing line unexecuted.

Added 2026-08-28, and they were the two this page had been naming as next:
`test_read_group` (123 test methods, the only coverage of the five
`read_group/` units) and `test_access_rights` (54, record rules and ACLs).
Both were green before they were gated — 123 of 123 and 52 of 52 with one
environment skip — so neither is a repair; they are coverage that existed and
ran nowhere. **A suite outside the lane is a suite nobody runs**, and this page
had said so about these two for as long as it has listed them.

Nothing is now named as next. That is not the same as nothing being left: the
lane runs eleven addons out of hundreds, and R4 is about the kind of defect no
structural gate can reach rather than about the count.

Method counts, not line counts. A suite's size is an argument about what the
lane is missing, and raw lines churn on every edit inside it without moving that
argument — `test_orm` lost 68 lines between two runs an hour apart while its method
count did not move — quoted as method, not as a size, because the size is
stated once above and a second copy of it drifts.

### The limits of "enforced"

**The integration gate is the only lane that runs addon tests in Python.** All
sixty-six boundary checkers are structural and DB-free: they read import graphs,
call graphs, reached-member sets and documents. A change can satisfy all
sixty-six, and Tier 1 and Tier 2, and still be wrong — renaming `OrmCore`'s slots
(`cache`/`engine` → `_cache`/`_engine`) broke two DB-backed addon tests in
2026-08 while every gate and both DB-free tiers stayed green. Read a green
boundary job as "the structure holds", never as "the framework works".

**The JS suites have their own lane** (`.github/workflows/js_tests.yml`, added
2026-09-01). Until then no lane ran them: `WebSuite` and `MobileWebSuite` in
`addons/web/tests/test_js.py` are addon tests like any other, every integration
lane is `--stop-after-init` and most are `--no-http`, so both classes skipped
themselves at `setUpClass` and were reported as skipped, never as a pass and
never as a failure. The HOOT suites were a local gate, driven by `tooling/hoot`,
which made that runner's own advice the whole of the enforcement. The cost was
not hypothetical: a `mobile`-tagged test in `@web/ui/dialog_service` sat failing
from the day it landed, invisible because the desktop preset skips it by tag and
nothing else ran it at all, and `@hr/m2x_avatar_employee` failed 6 of 11 for as
long as nothing ran it.

The lane runs `tooling/hoot/hoot-shard` — the same plan `WebSuite` runs, read
from `test_js.py` rather than restated, one suite per page load — **under both
presets**, desktop and mobile, each against its own shard databases, because the
two presets select by tag and neither set is a superset of the other. Each pass
is gated on its own passed-test **count** as well as on the runner's exit code:
a suite contributing zero tests under a preset is not an error to the runner,
so a plan that narrowed to nothing would otherwise read as PASS. `./hoot` still
prints when a local selection owns tests the preset does not execute; that is
the nudge, and the lane is now the gate.

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
