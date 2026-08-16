import js_face_boundary as jfb


def _web_src(root, *dirs_and_files):
    src = root / "addons" / "web" / "static" / "src"
    for rel in dirs_and_files:
        p = src / rel
        if rel.endswith(".js"):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("export const x = 1;\n")
        else:
            p.mkdir(parents=True, exist_ok=True)
    return src


def _consumer(root, name, body):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return root


def test_an_import_past_a_face_is_a_violation(tmp_path):
    src = _web_src(tmp_path, "views/pivot", "views/pivot.js", "views/pivot/model.js")
    _consumer(
        tmp_path,
        "enterprise/web_studio/static/src/x.js",
        'import { M } from "@web/views/pivot/model";\n',
    )
    found = jfb.measure((tmp_path,), src)
    assert len(found) == 1
    assert found[0]["spec"] == "@web/views/pivot/model"
    assert found[0]["face"] == "@web/views/pivot"


def test_importing_the_face_itself_is_fine(tmp_path):
    src = _web_src(tmp_path, "views/pivot", "views/pivot.js", "views/pivot/model.js")
    _consumer(
        tmp_path,
        "enterprise/web_studio/static/src/x.js",
        'import { P } from "@web/views/pivot";\n',
    )
    assert jfb.measure((tmp_path,), src) == []


def test_a_directory_without_a_face_may_be_entered_anywhere(tmp_path):
    src = _web_src(tmp_path, "core/utils", "core/utils/timing.js")
    _consumer(
        tmp_path,
        "enterprise/web_studio/static/src/x.js",
        'import { debounce } from "@web/core/utils/timing";\n',
    )
    assert jfb.measure((tmp_path,), src) == []


def test_web_importing_its_own_internals_is_not_a_face_violation(tmp_path):
    src = _web_src(tmp_path, "views/pivot", "views/pivot.js", "views/pivot/model.js")
    _consumer(
        tmp_path,
        "addons/web/static/src/views/list/list_renderer.js",
        'import { M } from "@web/views/pivot/model";\n',
    )
    assert jfb.measure((tmp_path,), src) == []


def test_the_test_helper_escape_hatch_is_ignored(tmp_path):
    src = _web_src(tmp_path, "views/pivot", "views/pivot.js", "views/pivot/model.js")
    _consumer(
        tmp_path,
        "enterprise/web_studio/static/tests/x.js",
        'import { x } from "@web/../tests/web_test_helpers";\n',
    )
    assert jfb.measure((tmp_path,), src) == []


def test_a_jsdoc_type_reference_is_not_an_import(tmp_path):
    src = _web_src(tmp_path, "views/pivot", "views/pivot.js", "views/pivot/model.js")
    _consumer(
        tmp_path,
        "enterprise/web_studio/static/src/x.js",
        '/** @param {import("@web/views/pivot/model").M} m */\nexport const f = (m) => m;\n',
    )
    assert jfb.measure((tmp_path,), src) == []


def test_a_jsdoc_type_reference_is_found_by_the_type_measurement(tmp_path):
    src = _web_src(tmp_path, "views/pivot", "views/pivot.js", "views/pivot/model.js")
    _consumer(
        tmp_path,
        "enterprise/web_studio/static/src/x.js",
        '/** @param {import("@web/views/pivot/model").M} m */\nexport const f = (m) => m;\n',
    )
    assert jfb.measure((tmp_path,), src) == []
    found = jfb.measure_type_reaches((tmp_path,), src)
    assert len(found) == 1
    assert found[0]["spec"] == "@web/views/pivot/model"
    assert found[0]["face"] == "@web/views/pivot"
    assert found[0]["line"] == 1


def test_a_runtime_import_is_not_reported_as_a_type_reach(tmp_path):
    src = _web_src(tmp_path, "views/pivot", "views/pivot.js", "views/pivot/model.js")
    _consumer(
        tmp_path,
        "enterprise/web_studio/static/src/x.js",
        'import { M } from "@web/views/pivot/model";\n'
        'const lazy = () => import("@web/views/pivot/model");\n',
    )
    assert jfb.measure_type_reaches((tmp_path,), src) == []
    assert len(jfb.measure((tmp_path,), src)) == 2


def test_a_type_reference_to_the_face_itself_is_not_a_reach(tmp_path):
    src = _web_src(tmp_path, "views/pivot", "views/pivot.js", "views/pivot/model.js")
    _consumer(
        tmp_path,
        "enterprise/web_studio/static/src/x.js",
        '/** @type {import("@web/views/pivot").M} */\nexport let m;\n',
    )
    assert jfb.measure_type_reaches((tmp_path,), src) == []


def test_the_type_measurement_finds_something_on_the_real_tree():
    found = jfb.measure_type_reaches()
    assert found, "no type reaches found at all — the scan reached nothing"
    assert all(v["spec"].startswith("@web/") for v in found)
    assert all(v["face"].startswith("@web/") for v in found)


def test_a_lib_directory_is_not_scanned(tmp_path):
    src = _web_src(tmp_path, "views/pivot", "views/pivot.js", "views/pivot/model.js")
    _consumer(
        tmp_path,
        "enterprise/web_studio/static/lib/vendor.js",
        'import { M } from "@web/views/pivot/model";\n',
    )
    assert jfb.measure((tmp_path,), src) == []


def test_a_face_is_a_sibling_file_not_an_index(tmp_path):
    src = _web_src(
        tmp_path, "views/pivot", "views/pivot/index.js", "views/graph", "views/graph.js"
    )
    assert jfb.faced_directories(src) == {"views/graph"}


def test_the_outermost_face_is_the_one_reported(tmp_path):
    src = _web_src(
        tmp_path,
        "core/network",
        "core/network.js",
        "core/network/inner",
        "core/network/inner.js",
        "core/network/inner/deep.js",
    )
    _consumer(
        tmp_path,
        "enterprise/web_studio/static/src/x.js",
        'import { d } from "@web/core/network/inner/deep";\n',
    )
    found = jfb.measure((tmp_path,), src)
    assert len(found) == 1
    assert found[0]["face"] == "@web/core/network"


def _violation(tmp_path):
    src = _web_src(tmp_path, "views/pivot", "views/pivot.js", "views/pivot/model.js")
    _consumer(
        tmp_path,
        "enterprise/web_studio/static/src/x.js",
        'import { M } from "@web/views/pivot/model";\n',
    )
    return src


def _redirect_to(monkeypatch, tmp_path, src):
    measure, faces = jfb.measure, jfb.faced_directories
    monkeypatch.setattr(jfb, "measure", lambda *a, **k: measure((tmp_path,), src))
    monkeypatch.setattr(jfb, "faced_directories", lambda *a, **k: faces(src))


def test_check_exits_nonzero_on_a_new_violation(tmp_path, monkeypatch):
    _redirect_to(monkeypatch, tmp_path, _violation(tmp_path))
    assert jfb.main(["--check"]) == 1


def test_a_pinned_violation_does_not_fail_the_gate(tmp_path, monkeypatch):
    _redirect_to(monkeypatch, tmp_path, _violation(tmp_path))
    monkeypatch.setitem(
        jfb.KNOWN_VIOLATIONS, "@web/views/pivot/model", "pinned by this test"
    )
    assert jfb.main(["--check"]) == 0


def test_report_mode_exits_zero_even_with_violations(tmp_path, monkeypatch):
    _redirect_to(monkeypatch, tmp_path, _violation(tmp_path))
    assert jfb.main([]) == 0


def test_the_real_tree_has_faces_to_check():
    assert len(jfb.faced_directories()) >= 30


def test_the_real_tree_holds_the_property_today():
    unpinned = [v for v in jfb.measure() if v["spec"] not in jfb.KNOWN_VIOLATIONS]
    assert unpinned == [], f"{len(unpinned)} import(s) now reach past a face"
