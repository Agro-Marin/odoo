import js_layer_cohesion as jlc


def _tree(root, files):
    static = root / "static"
    for rel, body in files.items():
        p = static / "src" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    (static / "src").mkdir(parents=True, exist_ok=True)
    return static


def _chain(layer, n, *, connected=True):
    out = {}
    for i in range(n):
        body = "" if i == 0 or not connected else f'import "./f{i - 1}.js";\n'
        out[f"{layer}/f{i}.js"] = body + "export const x = 1;\n"
    return out


def test_a_chain_has_no_isolated_files(tmp_path):
    static = _tree(tmp_path, _chain("core", 10))
    assert jlc.layer_stats(static)["core"] == (10, 0)


def test_files_that_import_nothing_are_all_isolated(tmp_path):
    static = _tree(tmp_path, _chain("bag", 10, connected=False))
    assert jlc.layer_stats(static)["bag"] == (10, 10)


def test_being_imported_counts_as_connected(tmp_path):
    static = _tree(
        tmp_path,
        {
            "core/a.js": 'import "./b.js";\nexport const a = 1;\n',
            "core/b.js": "export const b = 1;\n",
        },
    )
    assert jlc.layer_stats(static)["core"] == (2, 0)


def test_cross_layer_imports_do_not_count_as_cohesion(tmp_path):
    static = _tree(
        tmp_path,
        {
            "core/base.js": "export const base = 1;\n",
            **{
                f"bag/f{i}.js": 'import "@web/core/base.js";\nexport const x = 1;\n'
                for i in range(9)
            },
        },
    )
    assert jlc.layer_stats(static)["bag"] == (9, 9)


def test_bare_specifiers_are_not_edges(tmp_path):
    static = _tree(
        tmp_path,
        {f"bag/f{i}.js": 'import { Component } from "@odoo/owl";\n' for i in range(9)},
    )
    assert jlc.layer_stats(static)["bag"] == (9, 9)


def test_jsdoc_import_tags_are_not_edges(tmp_path):
    static = _tree(
        tmp_path,
        {
            "bag/types.js": '/** @import { X } from "./other.js" */\nexport const t = 1;\n',
            "bag/other.js": "export const o = 1;\n",
            **{f"bag/f{i}.js": "export const x = 1;\n" for i in range(7)},
        },
    )
    assert jlc.layer_stats(static)["bag"] == (9, 9)


def test_multiline_and_side_effect_and_reexport_forms_are_edges(tmp_path):
    static = _tree(
        tmp_path,
        {
            "core/target.js": "export const t = 1;\n",
            "core/multiline.js": 'import {\n    a,\n    b,\n} from "./target.js";\n',
            "core/sideeffect.js": 'import "./target.js";\n',
            "core/reexport.js": 'export { t } from "./target.js";\n',
        },
    )
    assert jlc.layer_stats(static)["core"] == (4, 0)


def test_a_layer_over_the_threshold_is_reported(tmp_path):
    static = _tree(tmp_path, _chain("bag", 10, connected=False))
    new, _ = jlc.find_drift(static, frozenset())
    assert [f.contract for f in new] == ["isolated-fraction"]
    assert "100%" in new[0].detail


def test_a_cohesive_layer_is_not_reported(tmp_path):
    static = _tree(tmp_path, _chain("core", 10))
    new, stale = jlc.find_drift(static, frozenset())
    assert new == [] and stale == []


def test_a_layer_below_the_size_floor_is_not_judged(tmp_path):
    static = _tree(tmp_path, _chain("tiny", 3, connected=False))
    new, _ = jlc.find_drift(static, frozenset())
    assert new == []


def test_pinned_debt_that_still_exists_is_tolerated(tmp_path):
    static = _tree(tmp_path, _chain("bag", 10, connected=False))
    new, stale = jlc.find_drift(static, frozenset({"bag"}))
    assert new == [] and stale == []


def test_pinned_debt_that_was_paid_fails_as_stale(tmp_path):
    static = _tree(tmp_path, _chain("bag", 10))
    new, stale = jlc.find_drift(static, frozenset({"bag"}))
    assert new == []
    assert [f.contract for f in stale] == ["stale-known"]
    assert "unpin" in stale[0].detail or "remove from" in stale[0].detail


def test_exempt_layers_are_not_measured(tmp_path):
    static = _tree(
        tmp_path, {f"scss/f{i}.js": "export const x = 1;\n" for i in range(9)}
    )
    assert "scss" not in jlc.layer_stats(static)


def test_an_absent_tree_refuses(tmp_path):
    import pytest

    with pytest.raises(SystemExit) as exc:
        jlc.main(["--check", "--web-static", str(tmp_path / "nothing")])
    assert exc.value.code == 2


def test_a_present_but_empty_tree_refuses(tmp_path):
    import pytest

    (tmp_path / "src").mkdir(parents=True)
    with pytest.raises(SystemExit) as exc:
        jlc.main(["--check", "--web-static", str(tmp_path)])
    assert exc.value.code == 2


def test_a_tree_holding_only_non_js_refuses(tmp_path):
    import pytest

    (tmp_path / "src" / "core").mkdir(parents=True)
    (tmp_path / "src" / "core" / "styles.scss").write_text("body { color: red; }\n")
    with pytest.raises(SystemExit) as exc:
        jlc.main(["--check", "--web-static", str(tmp_path)])
    assert exc.value.code == 2


def test_real_web_tree_is_scanned_and_carries_no_pinned_debt():
    stats = jlc.layer_stats(jlc.WEB_STATIC)
    assert stats["fields"][0] > 100, "expected the real fields/ layer to be found"
    assert not jlc.KNOWN_LOW_COHESION
    assert "services" not in stats
    new, stale = jlc.find_drift(jlc.WEB_STATIC)
    assert new == [], f"unpinned cohesion drift on HEAD: {new}"
    assert stale == [], f"pinned entries that are now cohesive: {stale}"


def test_threshold_still_separates_a_namespace_from_every_real_layer():
    stats = jlc.layer_stats(jlc.WEB_STATIC)
    judged = {
        layer: iso / total
        for layer, (total, iso) in stats.items()
        if total >= jlc.MIN_FILES
    }
    worst_layer = max(judged, key=lambda k: judged[k])
    assert judged[worst_layer] < jlc.MAX_ISOLATED_FRACTION, (
        f"{worst_layer} is at {judged[worst_layer]:.0%}, over the "
        f"{jlc.MAX_ISOLATED_FRACTION:.0%} threshold"
    )
    assert jlc.MAX_ISOLATED_FRACTION < 1.0 - 0.25
