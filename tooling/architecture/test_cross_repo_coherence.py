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
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "seed"],
        check=True,
    )
    return repo


def test_find_dangling_flags_runtime_import_only(tmp_path):
    repo = _init_consumer(tmp_path)
    removed = {"@web/fields/file_handler": "addons/web/static/src/fields/file_handler.js"}
    dangling = crc.find_dangling(removed, [repo])
    consumers = {d.consumer for d in dangling}
    assert "web_studio/static/src/uploader.js" in consumers
    # The JSDoc-only file must NOT be reported.
    assert "web_studio/static/src/typed.js" not in consumers


def test_find_dangling_clean_when_specifier_unused(tmp_path):
    repo = _init_consumer(tmp_path)
    removed = {"@web/fields/gone": "addons/web/static/src/fields/gone.js"}
    assert crc.find_dangling(removed, [repo]) == []
