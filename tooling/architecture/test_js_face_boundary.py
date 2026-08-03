"""Tests for the face-boundary gate.

Stdlib + pytest only — no Odoo imports — so this runs in the same
database-free way as the checker itself. Run with:

    pytest tooling/architecture/test_js_face_boundary.py

The measurement tests build synthetic trees, so they keep their meaning as the
real surface changes. The tests that read the real tree assert the two things a
measurement gate silently loses: that it found its inputs, and that the property
it exists to hold is actually held today.

The first test is the one that matters. A gate reporting ✓ on a tree with no
violations is indistinguishable from a gate that looked at nothing, so the
positive control — a synthetic bypass it MUST catch — is what gives the ✓ its
meaning.
"""

import js_face_boundary as jfb  # sys.path set by conftest.py


def _web_src(root, *dirs_and_files):
    """Build a fake `static/src`; a name ending in `.js` is a file."""
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


# --- the positive control: the gate can fail ---


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
    # `core/utils` deliberately has no face: it is a category, not a module.
    src = _web_src(tmp_path, "core/utils", "core/utils/timing.js")
    _consumer(
        tmp_path,
        "enterprise/web_studio/static/src/x.js",
        'import { debounce } from "@web/core/utils/timing";\n',
    )
    assert jfb.measure((tmp_path,), src) == []


# --- what is out of scope ---


def test_web_importing_its_own_internals_is_not_a_face_violation(tmp_path):
    # Inside the addon this is a layering question, which js_layer_check owns.
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
    # The whole reason the gates share one parser: a regex over "@web/..."
    # counts comments, and a type reference depends on nothing at runtime.
    src = _web_src(tmp_path, "views/pivot", "views/pivot.js", "views/pivot/model.js")
    _consumer(
        tmp_path,
        "enterprise/web_studio/static/src/x.js",
        '/** @param {import("@web/views/pivot/model").M} m */\nexport const f = (m) => m;\n',
    )
    assert jfb.measure((tmp_path,), src) == []


# --- type reaches: measured apart, never counted as violations ---


def test_a_jsdoc_type_reference_is_found_by_the_type_measurement(tmp_path):
    # The complement of the test above. `measure()` must keep ignoring it (that
    # decision is about runtime and is correct about runtime); this states that
    # the reach is nevertheless *visible*, because the face also promises the
    # files behind it can be renamed, and a rename does touch this consumer.
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
    # The two measurements partition the import forms; neither may double-count.
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
    # Same refusal-to-pass-vacuously contract as the empty-tree sweep: a scan
    # that reports nothing must be distinguishable from a scan that ran nothing.
    #
    # The COUNT is deliberately not pinned. These are advisory by construction
    # (`TYPE_REACHES_ARE_VIOLATIONS = False`), so asserting an exact number here
    # would fail the build for adding a legitimate type annotation — a gate with
    # teeth the surrounding design says it should not have.
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


# --- face discovery ---


def test_a_face_is_a_sibling_file_not_an_index(tmp_path):
    # `_specifier_to_static_url` appends `.js` and does no directory-index
    # resolution, so an index.js would be unreachable and is not a face.
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
    # Reporting the inner face would imply entering core/network was fine.
    assert found[0]["face"] == "@web/core/network"


# --- the exit code, which is the only part CI reads ---
#
# These exist because a manual probe caught what the measurement tests could
# not: `measure()` returning violations does not prove `main()` reports them.
# They patch the FUNCTION, never the module-global default — `consumer_roots=
# CONSUMER_ROOTS` binds at def time, so rebinding the global leaves the gate
# scanning the real tree and "passing". That is the same under-reach documented
# in test_every_gate_refuses_an_empty_tree, and it fooled the first probe here.


def _violation(tmp_path):
    src = _web_src(tmp_path, "views/pivot", "views/pivot.js", "views/pivot/model.js")
    _consumer(
        tmp_path,
        "enterprise/web_studio/static/src/x.js",
        'import { M } from "@web/views/pivot/model";\n',
    )
    return src


def _redirect_to(monkeypatch, tmp_path, src):
    """Point main() at the synthetic tree, keeping the real implementations."""
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
    """Without --check a gate prints and exits 0, so a CI call site that forgets
    the flag gates on nothing. Pinning it here makes that visible."""
    _redirect_to(monkeypatch, tmp_path, _violation(tmp_path))
    assert jfb.main([]) == 0


# --- the real tree ---


def test_the_real_tree_has_faces_to_check():
    """A gate whose input set is empty passes vacuously; assert it is not."""
    assert len(jfb.faced_directories()) >= 30


def test_the_real_tree_holds_the_property_today():
    """The reason this gate could be added at zero cost. If this ever fails,
    the fix is to route the consumer through the face — not to pin it."""
    unpinned = [v for v in jfb.measure() if v["spec"] not in jfb.KNOWN_VIOLATIONS]
    assert unpinned == [], f"{len(unpinned)} import(s) now reach past a face"
