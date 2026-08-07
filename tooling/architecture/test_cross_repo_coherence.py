"""Tests for the cross-repo symbol-coherence checker.

Stdlib + pytest only — no Odoo imports. Run with:

    pytest tooling/architecture/test_cross_repo_coherence.py
"""

import argparse
import subprocess
from pathlib import Path

import cross_repo_coherence as crc  # sys.path set by conftest.py

# --- path -> module specifier mapping ---------------------------------------


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


# --- ref resolution ---------------------------------------------------------


def _ns(**kw):
    return argparse.Namespace(from_ref=None, to_ref=None, **kw)


def test_resolve_refs_falls_back_on_zero_sha(monkeypatch):
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", "0" * 40)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", "abc123")
    from_ref, to_ref = crc._resolve_refs(argparse.Namespace(from_ref=None, to_ref=None))
    assert from_ref == crc.DEFAULT_FROM_REF  # zero sha -> base
    assert to_ref == "abc123"


def test_resolve_refs_explicit_args_win(monkeypatch):
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", "envfrom")
    args = argparse.Namespace(from_ref="argfrom", to_ref="argto")
    assert crc._resolve_refs(args) == ("argfrom", "argto")


def test_resolve_refs_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("PRE_COMMIT_FROM_REF", raising=False)
    monkeypatch.delenv("PRE_COMMIT_TO_REF", raising=False)
    args = argparse.Namespace(from_ref=None, to_ref=None)
    assert crc._resolve_refs(args) == (crc.DEFAULT_FROM_REF, crc.DEFAULT_TO_REF)


# --- find_dangling: the crux (runtime import counts, comment does not) ------


def _init_consumer(tmp_path: Path) -> Path:
    repo = tmp_path / "enterprise"
    src = repo / "web_studio" / "static" / "src"
    src.mkdir(parents=True)
    # A real runtime import of the removed specifier -> must be flagged.
    (src / "uploader.js").write_text(
        'import { FileHandler } from "@web/fields/file_handler";\n'
        "export const x = FileHandler;\n",
        encoding="utf-8",
    )
    # A comment-only / JSDoc mention of the same specifier -> must be ignored.
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
    # The JSDoc-only file must NOT be reported.
    assert "web_studio/static/src/typed.js" not in consumers


def test_find_dangling_clean_when_specifier_unused(tmp_path):
    repo = _init_consumer(tmp_path)
    removed = {"@web/fields/gone": "addons/web/static/src/fields/gone.js"}
    assert crc.find_dangling(removed, [repo]) == []


# --- an unusable consumer repo must be LOUD, never a silent zero result ------

_REMOVED = {"@web/fields/file_handler": "addons/web/static/src/fields/file_handler.js"}


def test_find_dangling_reports_a_directory_that_is_not_a_git_repo(tmp_path, capsys):
    # The scan is `git grep`, so a plain directory yields nothing. Skipping it
    # silently is indistinguishable from "checked it and it was clean" -- the
    # exact failure the loud branch exists to prevent.
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


# --- step 2: a specifier core still provides is not a removal ---------------


def test_core_still_provides_existing_module():
    # `@web/core/domain` -> addons/web/static/src/core/domain.js, which exists.
    assert crc.core_still_provides("@web/core/domain")


def test_core_still_provides_false_for_absent_module():
    assert not crc.core_still_provides("@web/core/definitely_not_a_module")


# --- git output parsing: paths git does not print verbatim -------------------


_ODD_NAMES = ["café.js", "with space.js", "日本語.js", "plain.js"]


def _fixture_repo(tmp_path):
    """A core-shaped repo whose src/ holds names git will quote."""
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
    # git QUOTES any path outside plain ASCII by default (`core.quotePath`):
    # deleting src/café.js prints `D\t"addons/web/static/src/caf\303\251.js"`.
    # The leading quote alone stops `path_to_specifier` matching, so the
    # removal was dropped and its consumers were never checked — a pre-push
    # gate reporting "coherent" over the one removal it could not read.
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
    # A rename record is THREE NUL-separated fields (R100, old, new) while a
    # delete is two. Consuming only two leaves `new` to be read as the next
    # record's status, shifting everything after it — so a deletion following
    # a rename silently disappears.
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
    # `git grep -l` quotes too, and the quoted string names no file on disk —
    # the read then failed and the candidate was skipped by a suppressed
    # OSError, so the dangling import it held was never reported.
    root, git = _fixture_repo(tmp_path)
    (root / "addons/web/static/src/café.js").write_text(
        'import "@web/gone";\n', encoding="utf-8"
    )
    git("add", "-A")
    git("commit", "-qm", "import")
    found = crc._consumer_js_files_importing(root, "@web/gone")
    assert found
    assert all(path.is_file() for path in found)
