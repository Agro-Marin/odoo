"""Tests for the registry-mediated layering gate.

Stdlib + pytest only — no Odoo imports — so this runs in the same
database-free way as the checker itself. Run with:

    pytest tooling/architecture/test_js_registry_layering.py
"""

import js_layer_check as jlc  # sys.path set by tooling/conftest.py
import js_registry_layering as jrl


def _tree(monkeypatch, tmp_path, files):
    """Build a fake ``static/src`` from ``{relpath: source}`` and scan it."""
    for rel, body in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    monkeypatch.setattr(jrl, "WEB_SRC", tmp_path)
    return jrl.check()


PRODUCER = 'registry.category("services").add("thing", {});'


# --- the two gates must agree about what "upward" means -------------------


def test_layer_order_matches_the_import_gate():
    """If `js_layer_check` reorders its layers, this gate must not keep the
    old order and quietly grade edges against a contract nobody holds."""
    forbidden_by = {
        src: {f for c in jlc.CONTRACTS for f in c.forbidden if src in c.source}
        for src in jrl.LAYER_ORDER
    }
    for i, lower in enumerate(jrl.LAYER_ORDER):
        for higher in jrl.LAYER_ORDER[i + 1 :]:
            assert f"@web/{higher}" in forbidden_by[lower], (
                f"{lower} -> {higher} is upward here but not forbidden by "
                f"js_layer_check; the two gates disagree about the order"
            )


def test_ungoverned_layers_are_the_same_ones_the_import_gate_ignores():
    for name in ("boot", "public", "libs"):
        assert name not in jrl.RANK


# --- direction ------------------------------------------------------------


def test_an_upward_service_edge_is_an_inversion(monkeypatch, tmp_path):
    new, known = _tree(
        monkeypatch,
        tmp_path,
        {
            "webclient/thing_service.js": PRODUCER,
            "core/consumer.js": 'useService("thing");',
        },
    )
    assert [(i.module, i.service) for i in new] == [("core/consumer.js", "thing")]
    assert known == []


def test_a_downward_service_edge_is_not_an_inversion(monkeypatch, tmp_path):
    new, known = _tree(
        monkeypatch,
        tmp_path,
        {
            "core/thing_service.js": PRODUCER,
            "webclient/consumer.js": 'useService("thing");',
        },
    )
    assert (new, known) == ([], [])


def test_a_same_layer_service_edge_is_not_an_inversion(monkeypatch, tmp_path):
    new, known = _tree(
        monkeypatch,
        tmp_path,
        {
            "core/thing_service.js": PRODUCER,
            "core/other/consumer.js": 'useService("thing");',
        },
    )
    assert (new, known) == ([], [])


def test_an_ungoverned_consumer_is_skipped(monkeypatch, tmp_path):
    """`public/` sits outside the stack, exactly as in js_layer_check."""
    new, known = _tree(
        monkeypatch,
        tmp_path,
        {
            "webclient/thing_service.js": PRODUCER,
            "public/consumer.js": 'useService("thing");',
        },
    )
    assert (new, known) == ([], [])


def test_a_service_with_no_resolvable_producer_yields_no_edge(monkeypatch, tmp_path):
    new, known = _tree(monkeypatch, tmp_path, {"core/c.js": 'useService("ghost");'})
    assert (new, known) == ([], [])


# --- consumer forms -------------------------------------------------------


def test_env_services_dotted_form_resolves(monkeypatch, tmp_path):
    new, _ = _tree(
        monkeypatch,
        tmp_path,
        {
            "webclient/thing_service.js": PRODUCER,
            "core/consumer.js": "env.services.thing.doIt();",
        },
    )
    assert [i.module for i in new] == ["core/consumer.js"]


def test_services_bracket_form_resolves(monkeypatch, tmp_path):
    new, _ = _tree(
        monkeypatch,
        tmp_path,
        {
            "webclient/thing_service.js": PRODUCER,
            "core/consumer.js": 'services["thing"].doIt();',
        },
    )
    assert [i.module for i in new] == ["core/consumer.js"]


def test_a_commented_out_consumer_creates_no_edge(monkeypatch, tmp_path):
    """Comments are stripped before matching — a JSDoc mention is not an edge."""
    new, known = _tree(
        monkeypatch,
        tmp_path,
        {
            "webclient/thing_service.js": PRODUCER,
            "core/consumer.js": (
                '/** talks to useService("thing") one day */\n'
                '// useService("thing");\n'
                "export const x = 1;\n"
            ),
        },
    )
    assert (new, known) == ([], [])


def test_a_producer_consuming_its_own_service_is_not_an_edge(monkeypatch, tmp_path):
    new, known = _tree(
        monkeypatch,
        tmp_path,
        {"webclient/thing_service.js": PRODUCER + '\nuseService("thing");'},
    )
    assert (new, known) == ([], [])


# --- pinning --------------------------------------------------------------


def test_a_pinned_inversion_does_not_fail_the_gate(monkeypatch, tmp_path):
    monkeypatch.setattr(
        jrl,
        "KNOWN_INVERSIONS",
        (jrl.Known("core/consumer.js", "thing", "core", "webclient"),),
    )
    new, known = _tree(
        monkeypatch,
        tmp_path,
        {
            "webclient/thing_service.js": PRODUCER,
            "core/consumer.js": 'useService("thing");',
        },
    )
    assert new == []
    assert [i.module for i in known] == ["core/consumer.js"]


def test_a_pin_does_not_cover_the_same_pair_at_different_layers(
    monkeypatch, tmp_path
):
    """A pinned file that MOVES layer is a new inversion, not a covered one."""
    monkeypatch.setattr(
        jrl,
        "KNOWN_INVERSIONS",
        (jrl.Known("core/consumer.js", "thing", "core", "ui"),),
    )
    new, known = _tree(
        monkeypatch,
        tmp_path,
        {
            "webclient/thing_service.js": PRODUCER,
            "core/consumer.js": 'useService("thing");',
        },
    )
    assert [i.module for i in new] == ["core/consumer.js"]
    assert known == []


def test_the_pinned_entries_are_unique():
    seen = {(k.module, k.service) for k in jrl.KNOWN_INVERSIONS}
    assert len(seen) == len(jrl.KNOWN_INVERSIONS), "duplicate pin hides a real edge"


def test_every_pinned_layer_pair_is_genuinely_an_inversion():
    for k in jrl.KNOWN_INVERSIONS:
        assert jrl.RANK[k.consumer] < jrl.RANK[k.producer], (
            f"{k.module} pins {k.consumer} -> {k.producer}, which is not upward"
        )


# --- CLI contract ---------------------------------------------------------


def test_check_exits_nonzero_on_a_new_inversion(monkeypatch, tmp_path):
    monkeypatch.setattr(jrl, "KNOWN_INVERSIONS", ())
    for rel, body in {
        "webclient/thing_service.js": PRODUCER,
        "core/consumer.js": 'useService("thing");',
    }.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    monkeypatch.setattr(jrl, "WEB_SRC", tmp_path)
    assert jrl.main(["--check"]) == 1


def test_report_mode_exits_zero_even_with_inversions(monkeypatch, tmp_path):
    """Report mode is for humans; only --check gates. A CI call site that
    forgets the flag must be the thing that fails, not this."""
    monkeypatch.setattr(jrl, "KNOWN_INVERSIONS", ())
    for rel, body in {
        "webclient/thing_service.js": PRODUCER,
        "core/consumer.js": 'useService("thing");',
    }.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    monkeypatch.setattr(jrl, "WEB_SRC", tmp_path)
    assert jrl.main([]) == 0


def test_an_empty_tree_is_refused_rather_than_passed(monkeypatch, tmp_path):
    monkeypatch.setattr(jrl, "WEB_SRC", tmp_path)
    with __import__("pytest").raises(SystemExit) as exc:
        jrl.main(["--check"])
    assert exc.value.code != 0


# --- contract B: keyed lookups, and why enumeration is not one ------------


def _keyed(monkeypatch, tmp_path, files):
    monkeypatch.setattr(jrl, "KNOWN_INVERSIONS", ())
    monkeypatch.setattr(jrl, "KNOWN_KEYED_INVERSIONS", ())
    return _tree(monkeypatch, tmp_path, files)


def test_a_keyed_get_naming_a_higher_layer_item_is_an_inversion(
    monkeypatch, tmp_path
):
    new, _ = _keyed(
        monkeypatch,
        tmp_path,
        {
            "views/form/form_view.js": 'registry.category("views").add("form", {});',
            "fields/x.js": 'registry.category("views").get("form");',
        },
    )
    assert [(i.module, i.service, i.contract) for i in new] == [
        ("fields/x.js", "views:form", "keyed-lookup")
    ]


def test_enumerating_a_category_is_not_an_inversion(monkeypatch, tmp_path):
    """The plugin pattern: a reader that names no item depends on no producer.

    `ui/main_components_container.js` renders whatever registered; a
    `webclient/` item registering into it creates no ui -> webclient edge.
    Counting reader x producer pairs instead reports this as a violation, which
    is how a first measurement reached 79 against a real 14.
    """
    new, known = _keyed(
        monkeypatch,
        tmp_path,
        {
            "webclient/thing.js": 'registry.category("main_components").add("t", {});',
            "ui/container.js": (
                'const mainComponents = registry.category("main_components");\n'
                "for (const c of mainComponents.getAll()) { render(c); }\n"
            ),
        },
    )
    assert (new, known) == ([], [])


def test_a_keyed_get_through_a_bound_category_variable_resolves(
    monkeypatch, tmp_path
):
    """8 of the 14 real sites are only reachable through this form."""
    new, _ = _keyed(
        monkeypatch,
        tmp_path,
        {
            "views/kanban/kanban_view.js": 'registry.category("views").add("kanban", {});',
            "fields/x.js": (
                'const views = registry.category("views");\n'
                'export const K = views.get("kanban");\n'
            ),
        },
    )
    assert [i.service for i in new] == ["views:kanban"]


def test_a_downward_keyed_get_is_not_an_inversion(monkeypatch, tmp_path):
    new, known = _keyed(
        monkeypatch,
        tmp_path,
        {
            "core/thing.js": 'registry.category("dialogs").add("d", {});',
            "views/x.js": 'registry.category("dialogs").get("d");',
        },
    )
    assert (new, known) == ([], [])


def test_a_keyed_get_with_no_known_registrar_yields_no_edge(monkeypatch, tmp_path):
    new, known = _keyed(
        monkeypatch, tmp_path, {"core/x.js": 'registry.category("dialogs").get("ghost");'}
    )
    assert (new, known) == ([], [])


def test_the_same_key_twice_in_one_module_is_one_dependency(monkeypatch, tmp_path):
    new, _ = _keyed(
        monkeypatch,
        tmp_path,
        {
            "views/form/form_view.js": 'registry.category("views").add("form", {});',
            "fields/x.js": (
                'registry.category("views").get("form");\n'
                'registry.category("views").get("form");\n'
            ),
        },
    )
    assert len(new) == 1


def test_a_pinned_keyed_inversion_does_not_fail_the_gate(monkeypatch, tmp_path):
    monkeypatch.setattr(jrl, "KNOWN_INVERSIONS", ())
    monkeypatch.setattr(
        jrl,
        "KNOWN_KEYED_INVERSIONS",
        (jrl.KnownKeyed("fields/x.js", "views", "form", "fields", "views"),),
    )
    new, known = _tree(
        monkeypatch,
        tmp_path,
        {
            "views/form/form_view.js": 'registry.category("views").add("form", {});',
            "fields/x.js": 'registry.category("views").get("form");',
        },
    )
    assert new == []
    assert [i.service for i in known] == ["views:form"]


def test_every_pinned_keyed_layer_pair_is_genuinely_an_inversion():
    for k in jrl.KNOWN_KEYED_INVERSIONS:
        assert jrl.RANK[k.consumer] < jrl.RANK[k.producer], (
            f"{k.module} pins {k.consumer} -> {k.producer}, which is not upward"
        )


def test_the_pinned_keyed_entries_are_unique():
    seen = {(k.module, k.category, k.key) for k in jrl.KNOWN_KEYED_INVERSIONS}
    assert len(seen) == len(jrl.KNOWN_KEYED_INVERSIONS)


# --- contract B, third form: a category exported as a symbol ---------------
#
# `core/shared_components.js` exports its category as a binding, and six
# `views/` modules register into it while eight sites in `fields/` read from
# it. Until 2026-08-04 this gate saw none of that: the inline-`add` regex and
# the same-file-binding regex both miss it, so the seam laundered every
# dependency taken through it. These tests pin the shape, not the count.


def test_a_registration_through_an_imported_category_binding_is_seen(
    monkeypatch, tmp_path
):
    new, _ = _keyed(
        monkeypatch,
        tmp_path,
        {
            "core/shared_components.js": (
                'export const sharedComponents = registry.category("shared_components");'
            ),
            "views/view_button/view_button.js": (
                'import { sharedComponents } from "@web/core/shared_components";\n'
                'sharedComponents.add("ViewButton", ViewButton);\n'
            ),
            "fields/x.js": (
                'import { sharedComponents } from "@web/core/shared_components";\n'
                'export const B = sharedComponents.get("ViewButton");\n'
            ),
        },
    )
    assert [(i.module, i.service, i.contract) for i in new] == [
        ("fields/x.js", "shared_components:ViewButton", "keyed-lookup")
    ]


def test_an_aliased_import_of_a_category_binding_resolves(monkeypatch, tmp_path):
    """`import { sharedComponents as shared }` — the real form in x2many_dialog."""
    new, _ = _keyed(
        monkeypatch,
        tmp_path,
        {
            "core/shared_components.js": (
                'export const sharedComponents = registry.category("shared_components");'
            ),
            "views/form/form_utils.js": (
                'import { sharedComponents } from "@web/core/shared_components";\n'
                'sharedComponents.add("loadSubViews", loadSubViews);\n'
            ),
            "fields/x2many_dialog.js": (
                'import { sharedComponents as shared } from "@web/core/shared_components";\n'
                'await shared.get("loadSubViews")();\n'
            ),
        },
    )
    assert [i.service for i in new] == ["shared_components:loadSubViews"]


def test_enumeration_through_an_imported_binding_is_still_not_an_inversion(
    monkeypatch, tmp_path
):
    """Following the symbol must not cost the plugin pattern its exemption."""
    new, known = _keyed(
        monkeypatch,
        tmp_path,
        {
            "core/shared_components.js": (
                'export const sharedComponents = registry.category("shared_components");'
            ),
            "views/thing.js": (
                'import { sharedComponents } from "@web/core/shared_components";\n'
                'sharedComponents.add("t", t);\n'
            ),
            "ui/container.js": (
                'import { sharedComponents } from "@web/core/shared_components";\n'
                "for (const c of sharedComponents.getAll()) { render(c); }\n"
            ),
        },
    )
    assert (new, known) == ([], [])


def test_a_downward_read_through_an_imported_binding_is_not_an_inversion(
    monkeypatch, tmp_path
):
    new, known = _keyed(
        monkeypatch,
        tmp_path,
        {
            "core/shared_components.js": (
                'export const sharedComponents = registry.category("shared_components");'
            ),
            "core/thing.js": (
                'import { sharedComponents } from "@web/core/shared_components";\n'
                'sharedComponents.add("t", t);\n'
            ),
            "views/reader.js": (
                'import { sharedComponents } from "@web/core/shared_components";\n'
                'export const T = sharedComponents.get("t");\n'
            ),
        },
    )
    assert (new, known) == ([], [])


def test_a_non_web_import_specifier_is_ignored(monkeypatch, tmp_path):
    assert jrl.spec_to_rel("@odoo/owl") is None
    assert jrl.spec_to_rel("@web/core/shared_components") == (
        "core/shared_components.js"
    )


# --- the real tree ---
#
# Every test above monkeypatches ``WEB_SRC`` to a synthetic tree, so none of
# them proves the gate holds on the actual ``web`` sources. These two do -- the
# same shape ``test_js_face_boundary`` uses -- so a real inversion introduced by
# a future change fails pytest here, not only the ratchet step in CI.


def test_the_real_tree_has_registry_edges_to_check():
    """A gate whose input set is empty passes vacuously; assert it is not: the
    real tree carries both service consumers and keyed registry lookups for the
    layering rule to classify."""
    files = jrl.iter_source_files()
    assert len(files) > 100
    _producers, consumers = jrl.resolve(files)
    _registrars, lookups = jrl.resolve_keyed(files)
    assert len(consumers) + len(lookups) > 50


def test_the_real_tree_holds_the_property_today():
    """The reason this gate holds at zero new cost. If this ever fails, the fix
    is to route the consumer through the correct layer -- not to pin it."""
    new, known = jrl.check()
    assert new == [], f"{len(new)} new registry-layering inversion(s): " + ", ".join(
        f"{i.module} -> {i.service}" for i in new
    )
    # The pins are real edges the resolver found, not dead config: at least one
    # must still resolve, or the gate is silently classifying nothing.
    assert known, "no pinned inversion resolved -- the real-tree scan found nothing"
