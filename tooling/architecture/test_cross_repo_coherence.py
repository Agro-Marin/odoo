import argparse
import subprocess
from pathlib import Path

import cross_repo_coherence as crc


def test_path_to_specifier_web():
    assert (
        crc.path_to_specifier("addons/web/static/src/fields/file_handler.js")
        == "@web/fields/file_handler"
    )


def test_path_to_specifier_nested_module():
    assert (
        crc.path_to_specifier("addons/point_of_sale/static/src/app/store/models.js")
        == "@point_of_sale/app/store/models"
    )


def test_path_to_specifier_ignores_non_static_src():
    assert crc.path_to_specifier("addons/web/models/ir_model.py") is None
    assert crc.path_to_specifier("addons/web/static/tests/foo.js") is None
    assert crc.path_to_specifier("doc/whatever.js") is None


def _ns(**kw):
    return argparse.Namespace(from_ref=None, to_ref=None, **kw)


def test_resolve_refs_falls_back_on_zero_sha(monkeypatch):
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", "0" * 40)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", "abc123")
    monkeypatch.setattr(crc, "_default_from_ref", lambda: "origin/19.0-marin")
    from_ref, to_ref = crc._resolve_refs(argparse.Namespace(from_ref=None, to_ref=None))
    assert from_ref == "origin/19.0-marin"
    assert to_ref == "abc123"


def test_resolve_refs_explicit_args_win(monkeypatch):
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", "envfrom")
    args = argparse.Namespace(from_ref="argfrom", to_ref="argto")
    assert crc._resolve_refs(args) == ("argfrom", "argto")


def test_resolve_refs_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("PRE_COMMIT_FROM_REF", raising=False)
    monkeypatch.delenv("PRE_COMMIT_TO_REF", raising=False)
    monkeypatch.setattr(crc, "_default_from_ref", lambda: "origin/19.0-marin")
    args = argparse.Namespace(from_ref=None, to_ref=None)
    assert crc._resolve_refs(args) == ("origin/19.0-marin", crc.DEFAULT_TO_REF)


def test_default_from_ref_prefers_the_upstream_tracking_ref(monkeypatch):
    monkeypatch.setattr(crc, "_git", lambda *a: "origin/19.0-marin\n")
    assert crc._default_from_ref() == "origin/19.0-marin"


def test_default_from_ref_falls_back_without_an_upstream(monkeypatch):
    monkeypatch.setattr(crc, "_git", lambda *a: "")
    assert crc._default_from_ref() == crc.DEFAULT_FROM_REF


def test_the_default_range_is_not_empty_on_the_base_branch():
    head = crc._git(crc.ROOT, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if not head or head == "HEAD":  # pragma: no cover - detached checkout
        return
    assert crc._default_from_ref() != head


def _init_consumer(tmp_path: Path) -> Path:
    repo = tmp_path / "enterprise"
    src = repo / "web_studio" / "static" / "src"
    src.mkdir(parents=True)
    (src / "uploader.js").write_text(
        'import { FileHandler } from "@web/fields/file_handler";\n'
        "export const x = FileHandler;\n",
        encoding="utf-8",
    )
    (src / "typed.js").write_text(
        '/** @import { FileHandler } from "@web/fields/file_handler" */\n'
        'import { registry } from "@web/core/registry";\n'
        "export const y = registry;\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "seed",
        ],
        check=True,
    )
    return repo


def test_find_dangling_flags_runtime_import_only(tmp_path):
    repo = _init_consumer(tmp_path)
    removed = {
        "@web/fields/file_handler": "addons/web/static/src/fields/file_handler.js"
    }
    dangling = crc.find_dangling(removed, [repo])
    consumers = {d.consumer for d in dangling}
    assert "web_studio/static/src/uploader.js" in consumers
    assert "web_studio/static/src/typed.js" not in consumers


def test_find_dangling_clean_when_specifier_unused(tmp_path):
    repo = _init_consumer(tmp_path)
    removed = {"@web/fields/gone": "addons/web/static/src/fields/gone.js"}
    assert crc.find_dangling(removed, [repo]) == []


_REMOVED = {"@web/fields/file_handler": "addons/web/static/src/fields/file_handler.js"}


def test_find_dangling_reports_a_directory_that_is_not_a_git_repo(tmp_path, capsys):
    repo = tmp_path / "enterprise"
    src = repo / "web_studio" / "static" / "src"
    src.mkdir(parents=True)
    (src / "uploader.js").write_text(
        'import { FileHandler } from "@web/fields/file_handler";\n', encoding="utf-8"
    )
    assert crc.find_dangling(_REMOVED, [repo]) == []
    assert "NOT checked" in capsys.readouterr().err


def test_find_dangling_reports_a_missing_repo(tmp_path, capsys):
    assert crc.find_dangling(_REMOVED, [tmp_path / "absent"]) == []
    assert "not found, NOT checked" in capsys.readouterr().err


def test_core_still_provides_existing_module():
    assert crc.core_still_provides("@web/core/domain")


def test_core_still_provides_false_for_absent_module():
    assert not crc.core_still_provides("@web/core/definitely_not_a_module")


_ODD_NAMES = ["café.js", "with space.js", "日本語.js", "plain.js"]


def _fixture_repo(tmp_path):
    root = tmp_path / "core"
    src = root / "addons" / "web" / "static" / "src"
    src.mkdir(parents=True)

    def git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

    git("init", "-q", ".")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    for name in _ODD_NAMES:
        (src / name).write_text("export const x = 1;\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "init")
    git("branch", "-M", "19.0-marin")
    return root, git


def test_removed_specifiers_reads_paths_git_would_quote(tmp_path, monkeypatch):
    root, git = _fixture_repo(tmp_path)
    for name in _ODD_NAMES:
        git("rm", "-q", f"addons/web/static/src/{name}")
    git("commit", "-qm", "remove")
    monkeypatch.setattr(crc, "ROOT", root)
    removed = crc.removed_specifiers("19.0-marin~1", "HEAD")
    assert set(removed) == {f"@web/{n[:-3]}" for n in _ODD_NAMES}


def test_a_rename_reports_the_old_path_not_the_new_one(tmp_path, monkeypatch):
    root, git = _fixture_repo(tmp_path)
    git("mv", "addons/web/static/src/café.js", "addons/web/static/src/renamed.js")
    git("commit", "-qm", "rename")
    monkeypatch.setattr(crc, "ROOT", root)
    removed = crc.removed_specifiers("19.0-marin~1", "HEAD")
    assert "@web/café" in removed
    assert "@web/renamed" not in removed


def test_a_rename_does_not_desync_the_records_after_it(tmp_path, monkeypatch):
    root, git = _fixture_repo(tmp_path)
    git("mv", "addons/web/static/src/café.js", "addons/web/static/src/renamed.js")
    git("rm", "-q", "addons/web/static/src/plain.js")
    git("rm", "-q", "addons/web/static/src/日本語.js")
    git("commit", "-qm", "rename and remove")
    monkeypatch.setattr(crc, "ROOT", root)
    removed = crc.removed_specifiers("19.0-marin~1", "HEAD")
    assert removed.keys() >= {"@web/café", "@web/plain", "@web/日本語"}
    assert "@web/renamed" not in removed


def test_consumer_candidates_are_paths_that_exist(tmp_path):
    root, git = _fixture_repo(tmp_path)
    (root / "addons/web/static/src/café.js").write_text(
        'import "@web/gone";\n', encoding="utf-8"
    )
    git("add", "-A")
    git("commit", "-qm", "import")
    found = crc._consumer_js_files_importing(root, "@web/gone")
    assert found
    assert all(path.is_file() for path in found)


def _init_core(tmp_path: Path, barrel_body: str) -> Path:
    """A minimal core addons root exporting `barrel_body` from @web/model/barrel."""
    addons = tmp_path / "core_addons"
    src = addons / "web" / "static" / "src" / "model"
    src.mkdir(parents=True)
    (src / "barrel.js").write_text(barrel_body, encoding="utf-8")
    return addons


def _init_name_consumer(tmp_path: Path, import_line: str) -> Path:
    repo = tmp_path / "enterprise"
    src = repo / "web_map" / "static" / "src"
    src.mkdir(parents=True)
    (src / "map_model.js").write_text(
        f"{import_line}\nexport const x = 1;\n", encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "seed",
        ],
        check=True,
    )
    return repo


_CHANGED = {"@web/model/barrel": "addons/web/static/src/model/barrel.js"}


def test_find_dangling_names_flags_a_rename_the_consumer_missed(tmp_path):
    """The case the whole-module half is blind to by construction.

    The file still exists, so nothing is removed and `find_dangling` sees
    nothing; the NAME moved, and the consumer still imports the old one. This
    is the shape that killed web.assets_web when `resequence` became
    `resequenceRecords` and enterprise/web_map was not renamed with it.
    """
    core = _init_core(tmp_path, "export function resequenceRecords() {}\n")
    repo = _init_name_consumer(
        tmp_path, 'import { resequence } from "@web/model/barrel";'
    )
    dangling = crc.find_dangling_names(_CHANGED, [repo], addons_roots=[core])
    assert [(d.name, d.consumer) for d in dangling] == [
        ("resequence", "web_map/static/src/map_model.js")
    ]
    # Nothing was REMOVED -- the file is still there, so the whole-module half
    # is handed an empty set and has nothing to say. That is the blind spot.
    assert crc.find_dangling({}, [repo]) == []


def test_find_dangling_names_reads_the_imported_side_of_an_alias(tmp_path):
    """`import { a as b }` asks the module for `a`, not `b`.

    Reading the local name would have made the motivating incident invisible:
    it aliased the removed `resequence` TO the name that still exists.
    """
    core = _init_core(tmp_path, "export function resequenceRecords() {}\n")
    repo = _init_name_consumer(
        tmp_path,
        'import { resequence as resequenceRecords } from "@web/model/barrel";',
    )
    dangling = crc.find_dangling_names(_CHANGED, [repo], addons_roots=[core])
    assert [d.name for d in dangling] == ["resequence"]


def test_find_dangling_names_clean_when_the_consumer_was_renamed_too(tmp_path):
    core = _init_core(tmp_path, "export function resequenceRecords() {}\n")
    repo = _init_name_consumer(
        tmp_path, 'import { resequenceRecords } from "@web/model/barrel";'
    )
    assert crc.find_dangling_names(_CHANGED, [repo], addons_roots=[core]) == []


def test_find_dangling_names_follows_a_re_export(tmp_path):
    """The barrel names the export; the definition lives one file deeper."""
    core = _init_core(
        tmp_path, 'export { resequenceRecords } from "./resequence.js";\n'
    )
    (core / "web" / "static" / "src" / "model" / "resequence.js").write_text(
        "export function resequenceRecords() {}\n", encoding="utf-8"
    )
    ok = _init_name_consumer(
        tmp_path, 'import { resequenceRecords } from "@web/model/barrel";'
    )
    assert crc.find_dangling_names(_CHANGED, [ok], addons_roots=[core]) == []


def test_find_dangling_names_ignores_a_module_the_range_did_not_touch(tmp_path):
    core = _init_core(tmp_path, "export function resequenceRecords() {}\n")
    repo = _init_name_consumer(
        tmp_path, 'import { resequence } from "@web/model/barrel";'
    )
    assert crc.find_dangling_names({}, [repo], addons_roots=[core]) == []


def test_changed_specifiers_maps_modified_core_paths(monkeypatch):
    monkeypatch.setattr(
        crc,
        "_git",
        lambda *a: "addons/web/static/src/model/barrel.js\0addons/web/README.md\0",
    )
    assert crc.changed_specifiers("a", "b") == {
        "@web/model/barrel": "addons/web/static/src/model/barrel.js"
    }
