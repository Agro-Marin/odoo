"""Drift guard for the ``own_class_memo`` key registry (``ORM_CLASS_MEMOS``).

Registry model classes survive re-setup (registration only reassigns
``__bases__``), so every per-class memo written via
``helpers.own_class_memo(cls, "<key>", ...)`` must be discarded by
``registration._prepare_setup`` — which iterates ``helpers.ORM_CLASS_MEMOS``.
The call sites live in ``models/`` and pass their key as a string literal, so
nothing structural ties them to the registry: a seventh memo added elsewhere
would silently serve stale tuples across re-setups.  This test closes that
drift risk by scanning the ORM sources for every ``own_class_memo`` call and
asserting the literal key set equals ``ORM_CLASS_MEMOS`` exactly.  Mirrors
``test_field_access_preamble`` (source scan pinning a convention the code
cannot enforce), but needs the real import for the constant, hence Tier 2.
"""

import pathlib
import re

from odoo.orm.helpers import ORM_CLASS_MEMOS

_ORM_DIR = pathlib.Path(__file__).resolve().parent.parent

# a call site: ``own_class_memo(<receiver>, "<literal key>"`` — possibly split
# across lines (DOTALL lets \s* span newlines)
_CALL_WITH_LITERAL_KEY = re.compile(
    r"own_class_memo\(\s*[\w.]+\s*,\s*\"([A-Za-z_]+)\"", re.DOTALL
)
# any call at all (used to prove no call passes a non-literal key that the
# pattern above — and therefore the registry check — would silently miss)
_ANY_CALL = re.compile(r"own_class_memo\(")


def _iter_sources():
    for path in sorted(_ORM_DIR.rglob("*.py")):
        if "tests" in path.parts:
            continue
        yield path, path.read_text()


def test_every_memo_key_is_registered():
    keys: set[str] = set()
    for _path, text in _iter_sources():
        for match in _CALL_WITH_LITERAL_KEY.finditer(text):
            keys.add(match.group(1))
    assert keys == set(ORM_CLASS_MEMOS), (
        f"own_class_memo call-site keys {sorted(keys)} diverged from "
        f"helpers.ORM_CLASS_MEMOS {sorted(ORM_CLASS_MEMOS)}; register new memo "
        f"keys there so registration._prepare_setup discards them on re-setup"
    )


def test_every_call_site_uses_a_literal_key():
    # a dynamically-built key would evade the scan above AND could not be in
    # the static registry — forbid it outright
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
