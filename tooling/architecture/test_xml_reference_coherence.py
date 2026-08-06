"""Tests for the XML string-reference coherence gate.

Stdlib + pytest only — no Odoo imports — so this runs in the same
database-free way as the checker itself. Run with:

    pytest tooling/architecture/test_xml_reference_coherence.py

The detection tests build synthetic scope trees, so they keep their meaning
as the real pin shrinks. Provider extraction goes through the real espree
analyzer (a node subprocess), because the analyzer IS the part regressions
hit: the bound registration form and the single-quoted form were each missed
once, by the sibling registry gate's regex and by this gate's own first
prefilter respectively, and only a test through the real parser would have
caught either. The real-tree tests assert what a measurement gate silently
loses: that it found its inputs, and that the shipped pin is the tree's own.
"""

from collections import Counter

import pytest
import xml_reference_coherence as xrc  # sys.path set by conftest.py


def _write(root, rel, body):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return root


def _measure(*roots):
    """Run the full pipeline over synthetic scope roots.

    Returns ``(dangling refs, unverifiable counter)``. Bare paths take their
    directory name as scope, and a scope outside CLOSURES is judged against
    itself alone.
    """
    unverifiable = Counter()
    named = xrc._named_roots(roots)
    js_providers = xrc.collect_js_providers(named, unverifiable)
    templates, consumers, _ = xrc.collect_xml(named, unverifiable)
    present = [name for name, _ in named]
    dangling = xrc.resolve(js_providers, templates, consumers, xrc.judged(present))
    return dangling, unverifiable


def _entries(dangling):
    return {f"{ref.kind}:{ref.name}" for ref in dangling}


# --- the defect class: a renamed key breaks its XML consumers ---


def test_a_renamed_widget_key_dangles(tmp_path):
    # The motivating failure: JS renames its registry key, the view still
    # names the old one, nothing fails before runtime.
    root = tmp_path / "repo"
    _write(
        root,
        "mod/static/src/f.js",
        'import { registry } from "@web/core/registry";\n'
        'registry.category("fields").add("badge_v2", {});\n',
    )
    _write(
        root,
        "mod/views/v.xml",
        '<odoo><record model="ir.ui.view"><field name="arch" type="xml">'
        '<form><field name="state" widget="badge"/></form>'
        "</field></record></odoo>",
    )
    dangling, _ = _measure(root)
    assert _entries(dangling) == {"widget:badge"}


def test_a_provided_widget_key_does_not_dangle(tmp_path):
    root = tmp_path / "repo"
    _write(
        root,
        "mod/static/src/f.js",
        'registry.category("fields").add("badge", {});\n',
    )
    _write(
        root,
        "mod/views/v.xml",
        '<odoo><form><field name="state" widget="badge"/></form></odoo>',
    )
    dangling, _ = _measure(root)
    assert dangling == []


def test_a_missing_t_call_target_dangles(tmp_path):
    root = tmp_path / "repo"
    _write(
        root,
        "mod/static/src/a.xml",
        '<templates><t t-name="mod.Caller"><t t-call="mod.Gone"/></t></templates>',
    )
    dangling, _ = _measure(root)
    assert _entries(dangling) == {"t-call:mod.Gone"}


def test_t_call_and_t_inherit_resolve_against_t_name(tmp_path):
    root = tmp_path / "repo"
    _write(
        root,
        "mod/static/src/a.xml",
        '<templates><t t-name="mod.Base">x</t></templates>',
    )
    _write(
        root,
        "other/static/src/b.xml",
        "<templates>"
        '<t t-name="other.A"><t t-call="mod.Base"/></t>'
        '<t t-name="other.B" t-inherit="mod.Base" t-inherit-mode="primary">y</t>'
        "</templates>",
    )
    dangling, _ = _measure(root)
    assert dangling == []


def test_js_class_resolves_in_the_views_registry(tmp_path):
    root = tmp_path / "repo"
    _write(
        root,
        "mod/static/src/v.js",
        'registry.category("views").add("my_list", {});\n',
    )
    _write(
        root,
        "mod/views/v.xml",
        '<odoo><list js_class="my_list"/><list js_class="gone_list"/></odoo>',
    )
    dangling, _ = _measure(root)
    assert _entries(dangling) == {"js_class:gone_list"}


def test_a_widget_element_resolves_in_view_widgets(tmp_path):
    root = tmp_path / "repo"
    _write(
        root,
        "mod/static/src/w.js",
        'registry.category("view_widgets").add("ribbon", {});\n',
    )
    _write(
        root,
        "mod/views/v.xml",
        '<odoo><form><widget name="ribbon"/><widget name="gone"/></form></odoo>',
    )
    dangling, _ = _measure(root)
    assert _entries(dangling) == {"view_widget:gone"}


# --- provider extraction: the forms a regex historically missed ---


def test_a_bound_registration_is_still_a_provider(tmp_path):
    # `const r = registry.category("views"); r.add(...)` — the form
    # js_registry_layering's inline regex documents having missed.
    root = tmp_path / "repo"
    _write(
        root,
        "mod/static/src/v.js",
        'const r = registry.category("views");\n'
        'r.add("bound_list", {}).add("chained_kanban", {});\n',
    )
    _write(
        root,
        "mod/views/v.xml",
        '<odoo><list js_class="bound_list"/><kanban js_class="chained_kanban"/></odoo>',
    )
    dangling, _ = _measure(root)
    assert dangling == []


def test_a_single_quoted_registration_is_still_a_provider(tmp_path):
    # Regression: the first prefilter matched only double-quoted needles, so
    # every `category('views')` file never reached espree and its keys read
    # as dangling (hr_expense, lunch, helpdesk...).
    root = tmp_path / "repo"
    _write(
        root,
        "mod/static/src/v.js",
        "registry.category('views').add('sq_list', {});\n",
    )
    _write(root, "mod/views/v.xml", '<odoo><list js_class="sq_list"/></odoo>')
    dangling, _ = _measure(root)
    assert dangling == []


def test_register_field_spec_expands_view_prefix_and_aliases(tmp_path):
    # This fork's canonical registration (fields/_registry.js): the spec
    # object registers `view.name` plus every alias, and a view-prefixed key
    # also answers the bare widget name.
    root = tmp_path / "repo"
    _write(
        root,
        "mod/static/src/f.js",
        'registerField({ name: "url", view: "form", aliases: ["link"] }, {});\n',
    )
    _write(
        root,
        "mod/views/v.xml",
        "<odoo><form>"
        '<field name="a" widget="url"/><field name="b" widget="link"/>'
        '<field name="c" widget="nope"/>'
        "</form></odoo>",
    )
    dangling, _ = _measure(root)
    assert _entries(dangling) == {"widget:nope"}


# --- widget context: which registry `widget=` resolves in ---


def test_a_pivot_widget_resolves_in_formatters_not_fields(tmp_path):
    root = tmp_path / "repo"
    _write(
        root,
        "mod/static/src/f.js",
        'registry.category("formatters").add("pct", () => {});\n'
        'registry.category("fields").add("only_field", {});\n',
    )
    _write(
        root,
        "mod/views/v.xml",
        "<odoo><pivot>"
        '<field name="a" widget="pct"/><field name="b" widget="only_field"/>'
        "</pivot></odoo>",
    )
    dangling, _ = _measure(root)
    # `only_field` is a fields key; a pivot looks widgets up in `formatters`
    # (via field_codec), so naming it there is the silent-formatting bug.
    assert _entries(dangling) == {"widget_formatter:only_field"}


def test_a_grid_widget_resolves_in_grid_components(tmp_path):
    root = tmp_path / "repo"
    _write(
        root,
        "mod/static/src/f.js",
        'registry.category("grid_components").add("cell", {});\n',
    )
    _write(
        root,
        "mod/views/v.xml",
        '<odoo><grid><field name="a" widget="cell"/>'
        '<field name="b" widget="gone"/></grid></odoo>',
    )
    dangling, _ = _measure(root)
    assert _entries(dangling) == {"widget_grid:gone"}


def test_an_attribute_body_widget_is_unscoped_and_accepts_any_registry(tmp_path):
    # An <attribute> body targets an arch this file does not contain, so the
    # view type is unknowable; any widget registry satisfies it.
    root = tmp_path / "repo"
    _write(
        root,
        "mod/static/src/f.js",
        'registry.category("formatters").add("fmt_only", () => {});\n',
    )
    _write(
        root,
        "mod/views/v.xml",
        '<odoo><xpath expr="//field[@name=\'a\']" position="attributes">'
        '<attribute name="widget">fmt_only</attribute>'
        '<attribute name="widget">truly_gone</attribute>'
        '<attribute name="widget"/>'
        "</xpath></odoo>",
    )
    dangling, _ = _measure(root)
    # The empty body REMOVES the attribute — not a reference.
    assert _entries(dangling) == {"widget_unscoped:truly_gone"}


# --- test trees are one-way ---


def test_a_test_only_registration_cannot_mask_a_production_dangler(tmp_path):
    root = tmp_path / "repo"
    _write(
        root,
        "mod/static/tests/f.test.js",
        'registry.category("fields").add("test_widget", {});\n',
    )
    _write(
        root,
        "mod/views/v.xml",
        '<odoo><form><field name="a" widget="test_widget"/></form></odoo>',
    )
    dangling, _ = _measure(root)
    assert _entries(dangling) == {"widget:test_widget"}


def test_a_test_consumer_may_use_test_and_production_providers(tmp_path):
    root = tmp_path / "repo"
    _write(
        root,
        "mod/static/tests/f.test.js",
        'registry.category("fields").add("test_widget", {});\n',
    )
    _write(
        root,
        "mod/static/src/p.xml",
        '<templates><t t-name="mod.Prod">x</t></templates>',
    )
    _write(
        root,
        "mod/static/tests/t.xml",
        '<templates><t t-name="mod.T"><t t-call="mod.Prod"/></t></templates>',
    )
    dangling, _ = _measure(root)
    assert dangling == []


# --- unverifiable references are counted, never failed on ---


def test_a_dynamic_t_call_is_unverifiable_not_dangling(tmp_path):
    root = tmp_path / "repo"
    _write(
        root,
        "mod/static/src/a.xml",
        '<templates><t t-name="mod.A">'
        '<t t-call="{{ props.template }}"/><t t-call="pre#{suffix}fix"/>'
        "</t></templates>",
    )
    dangling, unverifiable = _measure(root)
    assert dangling == []
    assert unverifiable["dynamic t-call/t-inherit"] == 2


def test_a_computed_registration_key_is_unverifiable(tmp_path):
    root = tmp_path / "repo"
    _write(
        root,
        "mod/static/src/f.js",
        'registry.category("fields").add(KEY, {});\n',
    )
    _write(
        root,
        "mod/views/v.xml",
        '<odoo><form><field name="a" widget="something"/></form></odoo>',
    )
    dangling, unverifiable = _measure(root)
    assert unverifiable["dynamic JS registration key"] == 1
    # The computed key cannot vouch for anything: the reference still dangles.
    assert _entries(dangling) == {"widget:something"}


def test_an_unparsable_xml_file_is_counted_not_crashed_on(tmp_path):
    root = tmp_path / "repo"
    _write(root, "mod/views/broken.xml", "<odoo><unclosed></odoo>")
    _write(
        root,
        "mod/views/ok.xml",
        '<odoo><form><field name="a" widget="gone"/></form></odoo>',
    )
    dangling, unverifiable = _measure(root)
    assert unverifiable["unparsable XML file"] == 1
    assert _entries(dangling) == {"widget:gone"}


# --- scopes: judged only when the provider closure is present ---


def test_a_scope_without_its_closure_is_not_judged():
    # enterprise's providers include odoo's; with odoo absent the verdict
    # would depend on what happens to be checked out, so there is none.
    assert xrc.judged(["enterprise"]) == []
    assert xrc.judged(["odoo", "enterprise"]) == ["odoo", "enterprise"]
    assert xrc.judged(["odoo"]) == ["odoo"]
    assert xrc.judged(["odoo", "agromarin"]) == ["odoo"]


def test_a_cross_scope_provider_satisfies_a_downstream_consumer(tmp_path):
    # enterprise XML may name an odoo-provided widget: odoo is in its
    # closure. The judged() test above covers the reverse direction.
    odoo = tmp_path / "odoo"
    ent = tmp_path / "enterprise"
    _write(
        odoo,
        "mod/static/src/f.js",
        'registry.category("fields").add("badge", {});\n',
    )
    _write(
        ent,
        "helpdesk/views/v.xml",
        '<odoo><form><field name="a" widget="badge"/></form></odoo>',
    )
    dangling, _ = _measure(odoo, ent)
    assert dangling == []


def test_an_upstream_consumer_cannot_use_a_downstream_provider(tmp_path):
    # odoo XML naming an enterprise-only widget is a coherence break for this
    # repo alone — and it must read the same whether or not enterprise
    # happens to be checked out.
    odoo = tmp_path / "odoo"
    ent = tmp_path / "enterprise"
    _write(
        ent,
        "mod/static/src/f.js",
        'registry.category("fields").add("ent_only", {});\n',
    )
    _write(
        odoo,
        "mod/views/v.xml",
        '<odoo><form><field name="a" widget="ent_only"/></form></odoo>',
    )
    dangling, _ = _measure(odoo, ent)
    assert _entries(dangling) == {"widget:ent_only"}


# --- the pin ---


def test_growth_and_shrink_fail_per_scope():
    measured = {"widget:a": frozenset({"odoo"}), "widget:b": frozenset({"odoo"})}
    pinned = {"widget:b": frozenset({"odoo"}), "widget:c": frozenset({"odoo"})}
    new, gone = xrc.drift(measured, pinned, ["odoo"])
    assert new == {"odoo": ["widget:a"]}
    assert gone == {"odoo": ["widget:c"]}


def test_a_scope_not_judged_is_not_drifted():
    measured = {"widget:a": frozenset({"odoo"})}
    pinned = {
        "widget:a": frozenset({"odoo"}),
        "widget:b": frozenset({"enterprise"}),
    }
    new, gone = xrc.drift(measured, pinned, ["odoo"])
    assert (new, gone) == ({}, {})


def test_a_dangler_appearing_in_a_new_scope_is_growth_there():
    measured = {"widget:a": frozenset({"odoo", "enterprise"})}
    pinned = {"widget:a": frozenset({"odoo"})}
    new, gone = xrc.drift(measured, pinned, ["odoo", "enterprise"])
    assert new == {"enterprise": ["widget:a"]}
    assert gone == {}


def test_pin_roundtrip_is_sorted_with_scope_provenance(tmp_path):
    pin = tmp_path / "pin.txt"
    xrc.write_pinned(
        {
            "widget:b": frozenset({"enterprise", "odoo"}),
            "t-call:mod.A": frozenset({"agromarin"}),
        },
        pin,
    )
    assert xrc.load_pinned(pin) == {
        "t-call:mod.A": frozenset({"agromarin"}),
        "widget:b": frozenset({"odoo", "enterprise"}),
    }
    body = [
        line
        for line in pin.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert body == ["t-call:mod.A  agromarin", "widget:b  odoo enterprise"]


def test_comments_and_blanks_are_not_pins(tmp_path):
    pin = tmp_path / "pin.txt"
    pin.write_text("# c\n\nwidget:x  odoo enterprise\n")
    assert xrc.load_pinned(pin) == {"widget:x": frozenset({"odoo", "enterprise"})}


def test_update_refuses_a_partial_checkout(tmp_path, monkeypatch):
    # A partial update could only erase the absent scopes' entries — the
    # record of what dangles there.
    present = tmp_path / "odoo"
    _write(present, "mod/views/v.xml", "<odoo/>")
    monkeypatch.setattr(
        xrc,
        "SCOPES",
        (("odoo", present), ("enterprise", tmp_path / "not-there")),
    )
    with pytest.raises(SystemExit) as exc:
        xrc.main(["--update"])
    assert exc.value.code == 2


# --- the gate must actually reach the real tree ---


def test_real_tree_is_measured_and_matches_its_pin():
    unverifiable = Counter()
    named = xrc._named_roots(xrc.SCOPES)
    present = [name for name, _ in named]
    assert "odoo" in present, "the gate's own checkout must always be a scope"
    js_providers = xrc.collect_js_providers(named, unverifiable)
    templates, consumers, xml_scanned = xrc.collect_xml(named, unverifiable)
    assert xml_scanned > 1000, "expected the real XML tree to be found"
    assert len(consumers) > 1000, "expected real view-arch references"
    fields_keys = js_providers.get("odoo", {}).get("fields", (set(), set()))[0]
    assert "many2many_tags" in fields_keys, "a core widget key is missing"
    odoo_templates = templates.get("odoo", (set(), set()))[0]
    assert any(t.startswith("web.") for t in odoo_templates), (
        "web's own templates are missing"
    )
    pinned = xrc.load_pinned()
    # The pin FILE must exist (a gate with no baseline would pass against
    # nothing); an EMPTY pin is the goal state — every hand-verified dangler
    # fixed — so emptiness itself is not a failure.
    assert xrc.PINNED.is_file(), "no pin file — the gate would pass against nothing"
    dangling = xrc.resolve(js_providers, templates, consumers, xrc.judged(present))
    new, gone = xrc.drift(
        xrc.measured_provenance(dangling), pinned, xrc.judged(present)
    )
    assert (new, gone) == ({}, {}), (
        f"reference drift: { {s: v[:5] for s, v in new.items()} } new, "
        f"{ {s: v[:5] for s, v in gone.items()} } gone"
    )


def test_the_real_danglers_are_few_which_is_what_makes_the_pin_honest():
    # The pin is a hand-verified worklist, not a dumping ground. If it ever
    # grows past this bound, collection precision has regressed (the
    # single-quote prefilter miss alone produced 40+ false danglers) —
    # tighten the scan rather than raising the bound.
    assert len(xrc.load_pinned()) < 30


# --- refusal: a gate that reaches nothing must say so ---


def test_an_empty_tree_is_refused(tmp_path, monkeypatch):
    empty = tmp_path / "odoo"
    (empty / "mod").mkdir(parents=True)
    monkeypatch.setattr(xrc, "SCOPES", (("odoo", empty),))
    with pytest.raises(SystemExit) as exc:
        xrc.main(["--check"])
    assert exc.value.code == 2
