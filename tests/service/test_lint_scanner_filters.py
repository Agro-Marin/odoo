from pathlib import Path

import pytest

from odoo.libs.lint.scan import scan_byte_patterns


def _write(root: Path, rel: str, content: str = "x\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _scanned(root: Path, exclude: list[str] | None = None) -> list[str]:
    hits = scan_byte_patterns([str(root)], [".py"], [b"x"], exclude or [])
    return sorted(str(Path(path).relative_to(root)) for path, _line, _idx in hits)


def test_ignore_files_and_git_excludes_do_not_shrink_the_scan(tmp_path):
    _write(tmp_path, "a.py")
    _write(tmp_path, "sub/b.py")
    _write(tmp_path, "sub/.ignore", "b.py\n")
    _write(tmp_path, ".gitignore", "a.py\n")
    _write(tmp_path, ".git/HEAD", "ref: refs/heads/main\n")
    _write(tmp_path, ".git/info/exclude", "sub/\n")
    _write(tmp_path, ".hidden/c.py")
    assert _scanned(tmp_path) == [".hidden/c.py", "a.py", "sub/b.py"]


def test_an_excluded_directory_name_is_skipped_at_any_depth(tmp_path):
    _write(tmp_path, "keep.py")
    _write(tmp_path, "node_modules/drop.py")
    _write(tmp_path, "deep/node_modules/drop.py")
    assert _scanned(tmp_path, ["node_modules"]) == ["keep.py"]


def test_an_unreadable_root_is_an_error_not_an_empty_count(tmp_path):
    with pytest.raises(OSError):
        scan_byte_patterns([str(tmp_path / "missing")], [".py"], [b"x"], [])
