"""Tests for the JS layer-cohesion gate.

Stdlib + pytest only — no Odoo imports — so this runs in the same
database-free way as the checker itself. Run with:

    pytest tooling/architecture/test_js_layer_cohesion.py

Every test builds a synthetic ``static/src`` tree rather than asserting against
the real one, so the suite does not change meaning when the real debt is paid
down. The tests that *do* read the real tree assert the two properties a
measurement gate can silently lose: that it found its inputs at all, and that
its threshold still separates a namespace from every real layer.

The import parsing was checked against ``es-module-lexer`` over the real tree
when this gate was written — it agreed on every file both can see, and found
five more that a graph keyed on edges cannot represent at all (``core/utils/
patch.js`` imports nothing; ``model/types.js`` carries only JSDoc ``@import``).
That comparison needs node, so it is not automated here; the forms it verified
are pinned as synthetic cases above instead.
"""

import js_layer_cohesion as jlc  # sys.path set by conftest.py


def _tree(root, files):
    """``files`` maps a path under ``src/`` to its source text."""
    static = root / "static"
    for rel, body in files.items():
        p = static / "src" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    (static / "src").mkdir(parents=True, exist_ok=True)
    return static


def _chain(layer, n, *, connected=True):
    """``n`` files in ``layer``; each imports the previous one when connected."""
    out = {}
    for i in range(n):
        body = "" if i == 0 or not connected else f'import "./f{i - 1}.js";\n'
        out[f"{layer}/f{i}.js"] = body + "export const x = 1;\n"
    return out


# --- the measurement itself ---


def test_a_chain_has_no_isolated_files(tmp_path):
    static = _tree(tmp_path, _chain("core", 10))
    assert jlc.layer_stats(static)["core"] == (10, 0)


def test_files_that_import_nothing_are_all_isolated(tmp_path):
    static = _tree(tmp_path, _chain("bag", 10, connected=False))
    assert jlc.layer_stats(static)["bag"] == (10, 10)


def test_being_imported_counts_as_connected(tmp_path):
    # Isolation is about having no relationship either way, so a file nothing
    # imports but which is itself imported is NOT isolated. Counting only
    # outgoing edges would call every leaf a namespace member.
    static = _tree(
        tmp_path,
        {
            "core/a.js": 'import "./b.js";\nexport const a = 1;\n',
            "core/b.js": "export const b = 1;\n",
        },
    )
    assert jlc.layer_stats(static)["core"] == (2, 0)


def test_cross_layer_imports_do_not_count_as_cohesion(tmp_path):
    # The whole point: depending on the layers below you is what layers are
    # for, and must not be mistaken for internal structure.
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
    # A types file referencing a sibling in `@import` has no runtime dependency
    # on it; counting those would make a layer of pure type references look
    # connected. This is why the checker strips comments first.
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


# --- the contract ---


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
    # Two files that do not import each other is not evidence of anything.
    static = _tree(tmp_path, _chain("tiny", 3, connected=False))
    new, _ = jlc.find_drift(static, frozenset())
    assert new == []


def test_pinned_debt_that_still_exists_is_tolerated(tmp_path):
    static = _tree(tmp_path, _chain("bag", 10, connected=False))
    new, stale = jlc.find_drift(static, frozenset({"bag"}))
    assert new == [] and stale == []


def test_pinned_debt_that_was_paid_fails_as_stale(tmp_path):
    # Shrink-only: paying a pin down must be a visible edit, so a clean-but-
    # still-pinned entry fails exactly like new drift.
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


# --- the gate must actually reach the real tree ---


def test_an_absent_tree_refuses(tmp_path):
    import pytest

    with pytest.raises(SystemExit) as exc:
        jlc.main(["--check", "--web-static", str(tmp_path / "nothing")])
    assert exc.value.code == 2


def test_a_present_but_empty_tree_refuses(tmp_path):
    # The distinction this gate got wrong. 61aa19e2712 probed every gate here
    # with an ABSENT tree and cleared this one, because `src/`.is_dir() is False
    # then. Present-and-empty is the case that actually happens — an exclude or
    # glob change that empties the file list leaves the directory standing — and
    # against that the old guard passed with "No new cohesion drift. ✓".
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
    # Guards the failure mode every gate here exists for: scanning nothing and
    # reporting success. The size assertion is what proves the real tree was
    # reached rather than an empty one.
    stats = jlc.layer_stats(jlc.WEB_STATIC)
    assert stats["fields"][0] > 100, "expected the real fields/ layer to be found"
    # `services/` was this gate's reason to exist and no longer exists. Keeping
    # the pin set empty is what makes a NEW namespace visible as new.
    assert not jlc.KNOWN_LOW_COHESION
    assert "services" not in stats
    new, stale = jlc.find_drift(jlc.WEB_STATIC)
    assert new == [], f"unpinned cohesion drift on HEAD: {new}"
    assert stale == [], f"pinned entries that are now cohesive: {stale}"


def test_threshold_still_separates_a_namespace_from_every_real_layer():
    # This replaces a margin test that asserted 10 clear points below the
    # threshold. That premise died with `services/`: the 17 registration-only
    # modules it held are reached through useService() and import nothing, so
    # they read as isolated wherever they sit. Dissolving the namespace spread
    # them over their host layers and lifted several fractions a few points —
    # `ui` 22% -> 26% — with nothing having got worse.
    #
    # So the metric detects CONCENTRATION of mechanism-grouped files, not their
    # existence, and with no namespace left there is no upper anchor to derive a
    # margin from. What remains checkable is the separation itself: every real
    # layer under the threshold, and a directory that is nothing but
    # registration-only files (100% isolated, as `services/` was at the end)
    # over it.
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
    # A pure namespace must still be caught, by a wide margin.
    assert jlc.MAX_ISOLATED_FRACTION < 1.0 - 0.25
