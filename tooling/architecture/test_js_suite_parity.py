"""Tests for the JS suite/source parity gate.

Stdlib + pytest only — no Odoo imports — so this runs in the same
database-free way as the checker itself. Run with:

    pytest tooling/architecture/test_js_suite_parity.py

Every test builds a synthetic ``static/`` tree rather than asserting against the
real one, so the suite does not change meaning when the real debt is paid down.
The one test that *does* read the real tree asserts only that the gate finds
inputs and reports a verdict — the property that ``hoot --all`` and an
over-narrow ESLint glob both failed, each reporting success having scanned
nothing.
"""

import js_suite_parity as jsp  # sys.path set by conftest.py


def _tree(root, src_files=(), test_files=()):
    """Build a synthetic ``static/`` tree; returns the ``static`` path."""
    static = root / "static"
    for rel in src_files:
        p = static / "src" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("export const x = 1;\n")
    for rel in test_files:
        p = static / "tests" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("test('x', () => {});\n")
    (static / "src").mkdir(parents=True, exist_ok=True)
    (static / "tests").mkdir(parents=True, exist_ok=True)
    return static


# --- contract A: a source layer must own a suite tree of its own name ---


def test_layer_with_source_but_no_suites_is_a_violation(tmp_path):
    # The D2 shape: source at widgets/, suites left behind at views/widgets/.
    # It trips BOTH contracts, and that is the point — the layer is
    # unaddressable (A) *and* the stranded suites are visible where they
    # actually sit (B), so the report names both the symptom and the cause.
    static = _tree(
        tmp_path,
        src_files=["widgets/char.js", "widgets/relational/many2one.js"],
        test_files=["views/widgets/char.test.js"],
    )
    new, stale = jsp.find_drift(static, frozenset(), frozenset())
    assert stale == []
    by_contract = {f.contract: f for f in new}
    assert set(by_contract) == {"layer-coverage", "orphan-test-dir"}
    assert by_contract["layer-coverage"].path == "src/widgets/"
    assert "0 suites" in by_contract["layer-coverage"].detail
    assert by_contract["orphan-test-dir"].path == "tests/views/widgets/"


def test_layer_covered_by_a_nested_suite_is_satisfied(tmp_path):
    # Coverage is recursive: tests/widgets/relational/x.test.js covers widgets/.
    static = _tree(
        tmp_path,
        src_files=["widgets/relational/many2one.js"],
        test_files=["widgets/relational/many2one.test.js"],
    )
    new, _ = jsp.find_drift(static, frozenset(), frozenset())
    assert new == []


def test_source_dir_without_js_is_not_required_to_have_suites(tmp_path):
    # scss/ and @types/ carry no JS and so cannot own a suite.
    static = _tree(tmp_path, src_files=["styles/app.scss"], test_files=[])
    new, _ = jsp.find_drift(static, frozenset(), frozenset())
    assert new == []


# --- contract B: a suite directory must have a source directory behind it ---


def test_orphan_test_dir_is_a_violation(tmp_path):
    static = _tree(
        tmp_path,
        src_files=["core/registry.js"],
        test_files=["core/registry.test.js", "nowhere/ghost.test.js"],
    )
    new, _ = jsp.find_drift(static, frozenset(), frozenset())
    assert [f.contract for f in new] == ["orphan-test-dir"]
    assert "tests/nowhere/" in new[0].path


def test_exempt_test_infrastructure_is_not_an_orphan(tmp_path):
    # _framework/, helpers/, mock_server/, tours/ mirror no source by design.
    static = _tree(
        tmp_path,
        src_files=["core/registry.js"],
        test_files=[
            "core/registry.test.js",
            "_framework/setup.test.js",
            "helpers/dom.test.js",
            "mock_server/mock_model.test.js",
            "tours/tour.test.js",
        ],
    )
    new, _ = jsp.find_drift(static, frozenset(), frozenset())
    assert new == []


def test_test_dir_without_suites_is_not_an_orphan(tmp_path):
    # A directory holding only fixtures is not a suite location.
    static = _tree(
        tmp_path, src_files=["core/registry.js"], test_files=["core/registry.test.js"]
    )
    (static / "tests" / "fixtures").mkdir(parents=True)
    (static / "tests" / "fixtures" / "data.js").write_text("export const d = [];\n")
    new, _ = jsp.find_drift(static, frozenset(), frozenset())
    assert new == []


def test_root_level_test_files_are_not_orphans(tmp_path):
    # tests/env.test.js mirrors src/env.js; the tests root is not a "directory
    # without a source counterpart".
    static = _tree(tmp_path, src_files=["env.js"], test_files=["env.test.js"])
    new, _ = jsp.find_drift(static, frozenset(), frozenset())
    assert new == []


# --- drift-zero: the pinned lists may only shrink ---


def test_pinned_debt_that_is_fixed_fails_as_stale(tmp_path):
    # A shrink-only list that is never shrunk is an allowlist. Paying debt down
    # must be a visible edit, so a clean-but-still-pinned entry fails too.
    static = _tree(
        tmp_path,
        src_files=["views/fields/char.js"],
        test_files=["views/fields/char.test.js"],
    )
    new, stale = jsp.find_drift(static, frozenset(), frozenset({"views/fields"}))
    assert new == []
    assert [f.contract for f in stale] == ["stale-known"]
    assert "unpin" in stale[0].detail or "remove from" in stale[0].detail


def test_pinned_debt_that_still_exists_is_tolerated(tmp_path):
    static = _tree(
        tmp_path,
        src_files=["core/registry.js"],
        test_files=["core/registry.test.js", "nowhere/ghost.test.js"],
    )
    new, stale = jsp.find_drift(static, frozenset(), frozenset({"nowhere"}))
    assert new == [] and stale == []


# --- the gate must actually reach the real tree ---


def test_real_web_tree_is_scanned_and_fields_is_covered():
    # Guards against the failure mode this whole file exists for: a gate that
    # scans nothing and reports success. The size assertion is what proves the
    # real tree was reached rather than an empty one.
    layers = jsp._src_layers(jsp.WEB_STATIC)
    assert layers["fields"] > 100, "expected the real fields/ layer to be found"
    # `fields` was the drift this gate was written for: 114 source files whose
    # 84 suites answered to `@web/views/fields`, so `@web/fields` selected
    # nothing. The suites have moved; keeping it out of the pinned set is what
    # stops that from coming back unnoticed.
    assert "fields" not in jsp.KNOWN_UNCOVERED_LAYERS
    new, stale = jsp.find_drift(jsp.WEB_STATIC)
    assert new == [], f"unpinned parity drift on HEAD: {new}"
    assert stale == [], f"pinned entries that are now clean: {stale}"


# --- the per-directory report: what sits BELOW contract A's resolution ---


def test_per_directory_report_accepts_a_mirrored_suite_dir(tmp_path):
    static = _tree(
        tmp_path,
        src_files=["views/list/list_renderer.js"],
        test_files=["views/list/list_renderer.test.js"],
    )
    assert jsp.uncovered_directories(static) == []


def test_per_directory_report_accepts_a_sibling_face_suite(tmp_path):
    """`components/autocomplete/` is addressed by `tests/components/autocomplete.test.js`.

    Checking only for a mirrored DIRECTORY reported ~2.5x the real number, which
    is the whole reason this helper exists rather than a one-line rglob.
    """
    static = _tree(
        tmp_path,
        src_files=["components/autocomplete/autocomplete.js"],
        test_files=["components/autocomplete.test.js"],
    )
    assert jsp.uncovered_directories(static) == []


def test_per_directory_report_accepts_a_per_file_sibling_suite(tmp_path):
    static = _tree(
        tmp_path,
        src_files=["ui/dialog/dialog_service.js"],
        test_files=["ui/dialog_service.test.js"],
    )
    assert jsp.uncovered_directories(static) == []


def test_per_directory_report_names_a_directory_no_suite_reaches(tmp_path):
    static = _tree(
        tmp_path,
        src_files=["ui/notification/notification_service.js"],
        test_files=["ui/dialog/dialog.test.js"],
    )
    assert [rel for rel, _f, _l in jsp.uncovered_directories(static)] == [
        "ui/notification"
    ]


def test_per_directory_report_ignores_a_directory_holding_no_js(tmp_path):
    static = _tree(tmp_path, src_files=["ui/theme/styles.scss"], test_files=[])
    assert jsp.uncovered_directories(static) == []


def test_per_directory_report_honours_the_exempt_source_dirs(tmp_path):
    static = _tree(tmp_path, src_files=["scss/base.js"], test_files=[])
    assert jsp.uncovered_directories(static) == []


def test_per_directory_report_counts_files_and_lines(tmp_path):
    static = _tree(tmp_path, src_files=["ui/block/block.js"], test_files=[])
    assert jsp.uncovered_directories(static) == [("ui/block", 1, 1)]


def test_per_directory_mode_is_a_report_and_never_gates(tmp_path, capsys):
    """It exits 0 even with uncovered directories: only --check gates."""
    static = _tree(tmp_path, src_files=["ui/block/block.js"], test_files=[])
    assert jsp.main(["--per-directory", "--web-static", str(static)]) == 0
    assert "ui/block" in capsys.readouterr().out


# --- registered-name hints: the other half of the per-directory report ---


def _write(static, rel, body):
    p = static / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_hint_finds_a_widget_reached_only_by_its_registry_key(tmp_path):
    """The `user_groups` shape: no mirrored suite, no import, but exercised.

    This is the gap that turned a selectability report into a false coverage
    alarm on 2026-08-03.
    """
    static = _tree(tmp_path)
    _write(
        static,
        "src/fields/specialized/user_groups/f.js",
        'registerField("res_user_group_ids", {});\n',
    )
    _write(
        static,
        "tests/webclient/res_user_group_ids_field.test.js",
        'test("x", () => { /* <field widget="res_user_group_ids"/> */ });\n',
    )
    uncovered = [rel for rel, _f, _l in jsp.uncovered_directories(static)]
    assert "fields/specialized/user_groups" in uncovered, (
        "it genuinely has no selector of its own — that number must not move"
    )
    hints = jsp.registered_name_hints(static, uncovered)
    assert hints["fields/specialized/user_groups"] == "res_user_group_ids"


def test_hint_is_absent_when_no_suite_names_the_key(tmp_path):
    static = _tree(tmp_path)
    _write(static, "src/a/f.js", 'registerField("never_used_widget", {});\n')
    _write(static, "tests/other/other.test.js", 'test("x", () => {});\n')
    uncovered = [rel for rel, _f, _l in jsp.uncovered_directories(static)]
    assert jsp.registered_name_hints(static, uncovered) == {}


def test_hint_covers_the_generic_registry_add_form(tmp_path):
    static = _tree(tmp_path)
    _write(
        static,
        "src/a/f.js",
        'registry.category("view_widgets").add("documentation_link", {});\n',
    )
    _write(static, "tests/b/b.test.js", 'test("x", () => "documentation_link");\n')
    uncovered = [rel for rel, _f, _l in jsp.uncovered_directories(static)]
    assert jsp.registered_name_hints(static, uncovered)["a"] == "documentation_link"


def test_hints_never_change_the_uncovered_count(tmp_path):
    """The hint annotates; it must not silently shrink the report."""
    static = _tree(tmp_path)
    _write(static, "src/a/f.js", 'registerField("w", {});\n')
    _write(static, "tests/b/b.test.js", 'test("x", () => "w");\n')
    before = jsp.uncovered_directories(static)
    jsp.registered_name_hints(static, [rel for rel, _f, _l in before])
    assert jsp.uncovered_directories(static) == before
