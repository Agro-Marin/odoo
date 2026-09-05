import os
from pathlib import Path

import _sources
import js_env_config_surface as env_config
import js_extension_surface as extension
import js_face_boundary as face
import js_field_record_surface as field_record
import js_public_surface as public
import pytest


def _write(path: Path, source: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "boundary", [".worktrees/old", "archive/clone", "archive/worktree"]
)
def test_nested_checkouts_do_not_change_consumer_measurements(
    tmp_path, monkeypatch, boundary
):
    source = (
        'import { Model } from "@web/views/pivot/model";\n'
        "export class Widget extends Model {\n"
        "  setup() { return this.env.config.activeKey; }\n"
        "}\nconst props = standardFieldProps;\n"
    )
    active = _write(tmp_path / "addons/consumer/static/src/widget.js", source)
    web_src = tmp_path / "addons/web/static/src"
    _write(web_src / "views/pivot.js")
    _write(web_src / "views/pivot/model.js")
    nested = tmp_path / boundary
    if boundary.endswith("clone"):
        (nested / ".git").mkdir(parents=True)
    elif boundary.endswith("worktree"):
        _write(nested / ".git", "gitdir: /elsewhere/worktrees/old\n")
    _write(
        nested / "addons/consumer/static/src/widget.js",
        source.replace("activeKey", "obsoleteKey"),
    )
    roots = (("probe", tmp_path),)
    assert env_config.measure(roots) == ({"activeKey": {"probe"}}, 0)
    assert public.measure(roots) == {"@web/views/pivot/model": 1}
    assert len(face.measure((tmp_path,), web_src)) == 1
    index = extension.Index(roots, web_src)
    assert set(index.files) == {
        active,
        web_src / "views/pivot.js",
        web_src / "views/pivot/model.js",
    }
    monkeypatch.setattr(field_record, "_named_roots", lambda: roots)
    assert field_record.widget_files() == [active]


def test_an_explicit_worktree_root_is_scanned(tmp_path):
    root = tmp_path / ".worktrees/selected"
    _write(root / ".git", "gitdir: /elsewhere/worktrees/selected\n")
    wanted = _write(root / "addons/example/model.py", "value = 1\n")
    _write(root / "node_modules/ignored/model.py", "value = 2\n")
    assert _sources.iter_python_files(root) == [wanted]


def test_nested_checkout_directories_are_pruned_before_descent(tmp_path, monkeypatch):
    nested = tmp_path / "archive/clone"
    (nested / ".git").mkdir(parents=True)
    _write(nested / "ignored.py")
    wanted = _write(tmp_path / "active.py")
    original = os.scandir

    def guarded(path):
        assert not Path(path).is_relative_to(nested), "entered a foreign checkout"
        return original(path)

    monkeypatch.setattr(os, "scandir", guarded)
    assert list(_sources.iter_files(tmp_path, "*.py")) == [wanted]
