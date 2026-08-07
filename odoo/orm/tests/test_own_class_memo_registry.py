import pathlib
import re

from odoo.orm.helpers import ORM_CLASS_MEMOS

_ORM_DIR = pathlib.Path(__file__).resolve().parent.parent

_CALL_WITH_LITERAL_KEY = re.compile(
    r"own_class_memo\(\s*[\w.]+\s*,\s*\"([A-Za-z_]+)\"", re.DOTALL
)
_ANY_CALL = re.compile(r"own_class_memo\(")


def _iter_sources():
    for path in sorted(_ORM_DIR.rglob("*.py")):
        if "tests" in path.parts:
            continue
        yield path, path.read_text()


def test_every_memo_key_is_registered():
    keys: set[str] = set()
    for _path, text in _iter_sources():
        keys.update(match.group(1) for match in _CALL_WITH_LITERAL_KEY.finditer(text))
    assert keys == set(ORM_CLASS_MEMOS), (
        f"own_class_memo call-site keys {sorted(keys)} diverged from "
        f"helpers.ORM_CLASS_MEMOS {sorted(ORM_CLASS_MEMOS)}; register new memo "
        f"keys there so registration._prepare_setup discards them on re-setup"
    )


def test_every_call_site_uses_a_literal_key():
    for path, text in _iter_sources():
        calls = len(_ANY_CALL.findall(text))
        literal = len(_CALL_WITH_LITERAL_KEY.findall(text))
        assert calls == literal, (
            f"{path}: {calls - literal} own_class_memo call(s) without a "
            f"string-literal key; keys must be literals listed in "
            f"helpers.ORM_CLASS_MEMOS"
        )


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
