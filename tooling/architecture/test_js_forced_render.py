import js_forced_render as jfr
import pytest

BLANKET = """/** @odoo-module native */

export function useModelWithSampleData(ModelClass, params) {
    const onUpdate = () => component.render(true);
    model.bus.addEventListener(ModelEvent.UPDATE, onUpdate);
}
"""

HEALTHY = """/** @odoo-module native */

export function useModelWithSampleData(ModelClass, params) {
    // propagation is the reactive graph; nothing forced
    useReactiveModel(model);
}
"""


@pytest.fixture
def tree(tmp_path):

    def write(rel, text, addon="web"):
        path = tmp_path / addon / "static" / "src" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    write.statics = lambda *addons: {
        a: tmp_path / a / "static" for a in (addons or ("web",))
    }
    write.root = tmp_path
    return write


def test_flags_the_blanket(tree):
    tree("model/model.js", BLANKET)
    findings, scanned, _ = jfr.find_forced_renders(tree.statics(), tree.root)
    assert scanned == 1
    assert [f.file for f in findings] == ["web/static/src/model/model.js"]
    assert findings[0].line == 4


def test_clean_tree_is_clean(tree):
    tree("model/model.js", HEALTHY)
    findings, scanned, _ = jfr.find_forced_renders(tree.statics(), tree.root)
    assert scanned == 1
    assert findings == []


def test_plain_render_is_not_flagged(tree):
    tree("a.js", "this.render();\nthis.render(false);\ncomp.render();\n")
    findings, _, _ = jfr.find_forced_renders(tree.statics(), tree.root)
    assert findings == []


def test_whitespace_variants_are_flagged(tree):
    tree("a.js", "this . render ( true )\n")
    findings, _, _ = jfr.find_forced_renders(tree.statics(), tree.root)
    assert len(findings) == 1


def test_non_literal_argument_is_out_of_scope(tree):
    tree("a.js", "this.render(force);\n")
    findings, _, _ = jfr.find_forced_renders(tree.statics(), tree.root)
    assert findings == []


def test_other_addons_are_counted_not_faulted(tree):
    tree("a.js", "this.render(true);\n", addon="documents")
    findings, scanned, elsewhere = jfr.find_forced_renders(
        tree.statics("documents"), tree.root
    )
    assert findings == []
    assert scanned == 0
    assert elsewhere == 1


def test_pinned_site_is_exempt(tree, monkeypatch):
    path = "web/static/src/fields/relational/x2many_dialog.js"
    tree("fields/relational/x2many_dialog.js", "this.render(true);\n")
    monkeypatch.setattr(
        jfr, "KNOWN_FORCED", (jfr.KnownForced(file=path, reason="test"),)
    )
    findings, _, _ = jfr.find_forced_renders(tree.statics(), tree.root)
    assert findings == []


def test_pin_is_file_scoped_not_global(tree, monkeypatch):
    monkeypatch.setattr(
        jfr,
        "KNOWN_FORCED",
        (jfr.KnownForced(file="web/static/src/pinned.js", reason="test"),),
    )
    tree("pinned.js", "this.render(true);\n")
    tree("other.js", "this.render(true);\n")
    findings, _, _ = jfr.find_forced_renders(tree.statics(), tree.root)
    assert [f.file for f in findings] == ["web/static/src/other.js"]


def test_every_pin_names_a_real_file_and_gives_a_reason():
    for known in jfr.KNOWN_FORCED:
        assert (jfr.ROOT / known.file).is_file(), known.file
        assert len(known.reason) > 40, known.file


def test_every_pin_is_still_needed():
    for known in jfr.KNOWN_FORCED:
        text = (jfr.ROOT / known.file).read_text(encoding="utf-8")
        assert jfr.FORCED_RENDER.search(text), (
            f"{known.file} no longer forces a render; remove it from KNOWN_FORCED"
        )


def test_empty_tree_scans_nothing(tree):
    findings, scanned, _ = jfr.find_forced_renders(tree.statics(), tree.root)
    assert (findings, scanned) == ([], 0)


def test_count_mode_reports_only_outside_web(tree, capsys):
    tree("a.js", "this.render(true);\n", addon="documents")
    tree("b.js", "this.render(true);\n", addon="web")
    findings, scanned, elsewhere = jfr.find_forced_renders(
        tree.statics("web", "documents"), tree.root
    )
    assert scanned == 1
    assert [f.file for f in findings] == ["web/static/src/b.js"]
    assert elsewhere == 1
