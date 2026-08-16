import js_layer_check as jlc


def test_matches_spec_is_prefix_boundary_not_substring():
    assert jlc._matches_spec("@web/fields/x", ("@web/fields",))
    assert jlc._matches_spec("@web/fields", ("@web/fields",))
    assert not jlc._matches_spec("@web/fields_extra/x", ("@web/fields",))
    assert not jlc._matches_spec("@web/core/x", ("@web/fields",))


def test_matches_path_is_prefix_boundary_not_substring():
    assert jlc._matches_path("core/utils/x.js", ("core",))
    assert not jlc._matches_path("core_legacy/x.js", ("core",))
    assert jlc._matches_path("core/domain.js", ("core/domain.js",))


def test_entity_below_feature_contract_exists():
    c = next(c for c in jlc.CONTRACTS if c.name == "entity-below-feature")
    assert c.source == ("model",)
    assert "@web/fields" in c.forbidden


def test_the_whole_layer_order_is_covered_by_some_contract():
    order = [
        "core",
        "ui",
        "components",
        "model",
        "fields",
        "search",
        "views",
        "webclient",
    ]
    forbidden_by = {
        src: {f for c in jlc.CONTRACTS for f in c.forbidden if src in c.source}
        for src in order
    }
    missing = [
        (lower, higher)
        for i, lower in enumerate(order)
        for higher in order[i + 1 :]
        if f"@web/{higher}" not in forbidden_by[lower]
    ]
    assert missing == [], f"layer steps no contract forbids: {missing}"


def test_a_violation_of_each_new_contract_would_be_caught():
    for name, module, spec in (
        ("core-below-ui-components", "core/x.js", "@web/ui/dialog/dialog"),
        ("ui-below-components", "ui/x.js", "@web/components/dropdown/dropdown"),
        (
            "components-below-entity",
            "components/x.js",
            "@web/model/relational_model/record",
        ),
        ("widget-order", "search/x.js", "@web/views/form/form_view"),
        ("widget-below-page", "views/x.js", "@web/webclient/webclient"),
    ):
        c = next(c for c in jlc.CONTRACTS if c.name == name)
        assert jlc._matches_path(module, c.source), name
        assert jlc._matches_spec(spec, c.forbidden), name


def test_normalise_spec_resolves_relative_to_the_web_form():

    assert jlc.normalise_spec("../views/utils", "core/domain.js") == "@web/views/utils"
    assert (
        jlc.normalise_spec("./utils/arrays", "core/domain.js")
        == "@web/core/utils/arrays"
    )
    assert jlc.normalise_spec("./x.js", "core/domain.js") == "@web/core/x"
    assert jlc.normalise_spec("./session", "env.js") == "@web/session"


def test_normalise_spec_ignores_what_is_not_a_web_module():
    assert jlc.normalise_spec("../../lib/luxon/luxon", "core/domain.js") is None
    assert jlc.normalise_spec("luxon", "core/domain.js") is None
    assert (
        jlc.normalise_spec("@mail/core/store", "core/domain.js") == "@mail/core/store"
    )


def test_relative_and_absolute_forms_produce_the_same_violations(tmp_path):
    src_dir = tmp_path / "addons" / "web" / "static" / "src" / "core"
    src_dir.mkdir(parents=True)
    web_src = tmp_path / "addons" / "web" / "static" / "src"

    def run(spec):
        (src_dir / "domain.js").write_text(f'import {{ x }} from "{spec}";\n')
        old_root, old_src = jlc.ROOT, jlc.WEB_SRC
        jlc.ROOT, jlc.WEB_SRC = tmp_path, web_src
        try:
            new, _ = jlc.check([src_dir / "domain.js"])
        finally:
            jlc.ROOT, jlc.WEB_SRC = old_root, old_src
        return sorted(v.contract for v in new), {v.imports for v in new}

    absolute = run("@web/views/utils")
    relative = run("../views/utils")
    assert relative == absolute
    assert absolute[0] == [
        "entity-below-widget-page",
        "shared-below-feature-widget-page",
    ]


def test_violation_records_how_the_import_is_written(tmp_path):
    web_src = tmp_path / "addons" / "web" / "static" / "src"
    (web_src / "core").mkdir(parents=True)
    target = web_src / "core" / "domain.js"
    target.write_text('import { x } from "../views/utils";\n')
    old_root, old_src = jlc.ROOT, jlc.WEB_SRC
    jlc.ROOT, jlc.WEB_SRC = tmp_path, web_src
    try:
        new, _ = jlc.check([target])
    finally:
        jlc.ROOT, jlc.WEB_SRC = old_root, old_src
    assert {v.written for v in new} == {"../views/utils"}
    target.write_text('import { x } from "@web/views/utils";\n')
    jlc.ROOT, jlc.WEB_SRC = tmp_path, web_src
    try:
        new, _ = jlc.check([target])
    finally:
        jlc.ROOT, jlc.WEB_SRC = old_root, old_src
    assert {v.written for v in new} == {""}


def test_real_tree_has_zero_new_violations():
    new, _known = jlc.check()
    assert new == [], "\n".join(
        f"{v.path}:{v.lineno}  {v.module} -> {v.imports} ({v.contract})" for v in new
    )


def test_the_gate_refuses_a_tree_it_cannot_find(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(jlc, "WEB_SRC", tmp_path / "nothing")
    with pytest.raises(SystemExit) as exc:
        jlc.main(["--check"])
    assert exc.value.code == 2
