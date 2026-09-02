from __future__ import annotations

import textwrap
from pathlib import Path

import py_class_length as gate
import pytest


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def _class_of(n_lines: int, name: str = "Big") -> str:
    methods = "\n".join(
        f"    def m{i}(self):\n        return {i}\n" for i in range(n_lines)
    )
    return f"class {name}:\n{methods}"


class TestMeasure:
    def test_a_class_at_the_budget_is_not_reported(self, tmp_path):
        src = _class_of((gate.MAX_LINES - 1) // 3)
        path = _write(tmp_path, "a.py", src)
        length = len(src.splitlines())
        assert length <= gate.MAX_LINES
        assert gate.measure([path]) == []

    def test_one_line_over_is_reported_with_its_excess(self, tmp_path):
        src = _class_of(gate.MAX_LINES // 3 + 1)
        path = _write(tmp_path, "a.py", src)
        length = len(src.splitlines())
        assert length > gate.MAX_LINES
        found = gate.measure([path])
        assert [c.what for c in found] == ["Big"]
        assert gate.excess_lines(found) == length - gate.MAX_LINES

    def test_nested_classes_are_measured_independently(self, tmp_path):
        inner = textwrap.indent(_class_of(gate.MAX_LINES // 3 + 1, "Inner"), "    ")
        src = f"class Outer:\n{inner}\n"
        path = _write(tmp_path, "a.py", src)
        assert sorted(c.what for c in gate.measure([path])) == ["Inner", "Outer"]

    def test_a_syntax_error_is_skipped_not_raised(self, tmp_path):
        path = _write(tmp_path, "a.py", "class Broken(:\n    pass\n")
        assert gate.measure([path]) == []

    def test_results_are_longest_first(self, tmp_path):
        a = _write(tmp_path, "a.py", _class_of(gate.MAX_LINES // 3 + 2, "A"))
        b = _write(tmp_path, "b.py", _class_of(gate.MAX_LINES // 3 + 9, "B"))
        assert [c.what for c in gate.measure([a, b])] == ["B", "A"]


def test_the_real_core_scope_scans_something():
    with pytest.raises(RuntimeError):
        gate.measure(src=Path("/nonexistent"))
    assert gate.iter_source_files(), "the core scope found no Python files"
