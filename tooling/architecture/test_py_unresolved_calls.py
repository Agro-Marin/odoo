from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import py_unresolved_calls as gate


def _measure(tmp_path: Path, **sources: str) -> list[gate.UnresolvedCall]:
    scope = tmp_path / "odoo"
    scope.mkdir(parents=True, exist_ok=True)
    for name, text in sources.items():
        (scope / f"{name}.py").write_text(text, encoding="utf-8")
    return gate.measure(scopes=(scope,))


def _names(found) -> list[str]:
    return sorted(c.name for c in found)


def test_a_call_to_nothing_is_reported(tmp_path):
    assert _names(_measure(tmp_path, a="self._vanished()\n")) == ["_vanished"]


def test_a_def_anywhere_in_scope_resolves_it(tmp_path):
    found = _measure(
        tmp_path,
        caller="self._helper()\n",
        elsewhere="class X:\n    def _helper(self):\n        return 1\n",
    )
    assert found == []


def test_a_class_name_resolves_it(tmp_path):
    assert _measure(tmp_path, a="class _Thing:\n    pass\n\n\nx._Thing()\n") == []


def test_an_attribute_binding_resolves_it(tmp_path):
    found = _measure(
        tmp_path,
        binder="obj._patched = lambda self: None\n",
        caller="self._patched()\n",
    )
    assert found == []


def test_an_annotated_attribute_binding_resolves_it(tmp_path):
    found = _measure(
        tmp_path,
        binder="class X:\n    obj._slot: int = 0\n",
        caller="self._slot()\n",
    )
    assert found == []


def test_a_bare_string_literal_resolves_it(tmp_path):
    found = _measure(
        tmp_path,
        decl='__slots__ = ("_lazy",)\n',
        caller="self._lazy()\n",
    )
    assert found == []


def test_a_name_merely_MENTIONED_inside_a_longer_string_does_not_resolve_it(tmp_path):
    found = _measure(
        tmp_path,
        prose='"""Nothing to do with it: _coincidence here"""\n',
        caller="self._coincidence()\n",
    )
    assert _names(found) == ["_coincidence"]


def test_a_dunder_is_not_a_private_call(tmp_path):
    assert _measure(tmp_path, a="self.__reduce__()\n") == []


def test_a_public_call_is_not_scanned(tmp_path):
    assert _measure(tmp_path, a="self.action_confirm()\n") == []


def test_a_bare_function_call_is_not_scanned(tmp_path):
    assert _measure(tmp_path, a="_helper()\n") == []


def test_the_external_allowlist_suppresses_its_entries(tmp_path):
    entry = next(iter(gate.EXTERNAL))
    assert _measure(tmp_path, a=f"self.{entry}()\n") == []


def test_every_external_entry_is_still_earning_its_place():
    assert gate.EXTERNAL, "the allowlist is empty; the probe would pass vacuously"
    assert all(name.startswith("_") for name in gate.EXTERNAL), (
        f"non-private names in EXTERNAL: "
        f"{sorted(n for n in gate.EXTERNAL if not n.startswith('_'))} -- the gate "
        f"never reports those, so the entry suppresses nothing"
    )


def test_test_files_are_scanned_unlike_the_sibling_counters(tmp_path):
    scope = tmp_path / "odoo"
    (scope / "tests").mkdir(parents=True)
    (scope / "tests" / "test_thing.py").write_text("self._gone()\n", encoding="utf-8")
    assert _names(gate.measure(scopes=(scope,))) == ["_gone"]


def test_an_empty_scan_refuses_instead_of_reporting_zero(tmp_path):
    with pytest.raises(RuntimeError, match="no Python sources"):
        gate.measure(scopes=(tmp_path / "absent",))


def test_findings_are_sorted_so_a_diff_is_readable(tmp_path):
    found = _measure(tmp_path, a="self._zeta()\nself._alpha()\n")
    assert _names(found) == ["_alpha", "_zeta"]
    assert [c.name for c in found] == ["_alpha", "_zeta"]
