import js_suite_parity as jsp


def _tree(root, src_files=(), test_files=()):
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


def test_layer_with_source_but_no_suites_is_a_violation(tmp_path):
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
    static = _tree(
        tmp_path,
        src_files=["widgets/relational/many2one.js"],
        test_files=["widgets/relational/many2one.test.js"],
    )
    new, _ = jsp.find_drift(static, frozenset(), frozenset())
    assert new == []


def test_source_dir_without_js_is_not_required_to_have_suites(tmp_path):
    static = _tree(tmp_path, src_files=["styles/app.scss"], test_files=[])
    new, _ = jsp.find_drift(static, frozenset(), frozenset())
    assert new == []


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
    static = _tree(
        tmp_path, src_files=["core/registry.js"], test_files=["core/registry.test.js"]
    )
    (static / "tests" / "fixtures").mkdir(parents=True)
    (static / "tests" / "fixtures" / "data.js").write_text("export const d = [];\n")
    new, _ = jsp.find_drift(static, frozenset(), frozenset())
    assert new == []


def test_root_level_test_files_are_not_orphans(tmp_path):
    static = _tree(tmp_path, src_files=["env.js"], test_files=["env.test.js"])
    new, _ = jsp.find_drift(static, frozenset(), frozenset())
    assert new == []


def test_pinned_debt_that_is_fixed_fails_as_stale(tmp_path):
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


def test_real_web_tree_is_scanned_and_fields_is_covered():
    layers = jsp._src_layers(jsp.WEB_STATIC)
    assert layers["fields"] > 100, "expected the real fields/ layer to be found"
    assert "fields" not in jsp.KNOWN_UNCOVERED_LAYERS
    new, stale = jsp.find_drift(jsp.WEB_STATIC)
    assert new == [], f"unpinned parity drift on HEAD: {new}"
    assert stale == [], f"pinned entries that are now clean: {stale}"


def test_per_directory_report_accepts_a_mirrored_suite_dir(tmp_path):
    static = _tree(
        tmp_path,
        src_files=["views/list/list_renderer.js"],
        test_files=["views/list/list_renderer.test.js"],
    )
    assert jsp.uncovered_directories(static) == []


def test_per_directory_report_accepts_a_sibling_face_suite(tmp_path):

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
    static = _tree(tmp_path, src_files=["ui/block/block.js"], test_files=[])
    assert jsp.main(["--per-directory", "--web-static", str(static)]) == 0
    assert "ui/block" in capsys.readouterr().out


def _write(static, rel, body):
    p = static / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_hint_finds_a_widget_reached_only_by_its_registry_key(tmp_path):

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
    static = _tree(tmp_path)
    _write(static, "src/a/f.js", 'registerField("w", {});\n')
    _write(static, "tests/b/b.test.js", 'test("x", () => "w");\n')
    before = jsp.uncovered_directories(static)
    jsp.registered_name_hints(static, [rel for rel, _f, _l in before])
    assert jsp.uncovered_directories(static) == before
