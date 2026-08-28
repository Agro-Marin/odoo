from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import py_x2many_count as gate


def _count(tmp_path: Path, source: str) -> list[gate.HandCount]:
    path = tmp_path / "models" / "thing.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return gate.measure(files=[path])


def test_a_hand_written_counter_is_found(tmp_path):
    found = _count(
        tmp_path,
        """
class Move:
    def _compute_lines_count(self):
        for move in self:
            move.lines_count = len(move.line_ids)
""",
    )
    assert [(f.kind, f.what) for f in found] == [
        ("len", "_compute_lines_count -> line_ids")
    ]


def test_search_count_in_a_loop_over_self_is_found(tmp_path):
    found = _count(
        tmp_path,
        """
class Move:
    def _compute_n(self):
        for move in self:
            move.n = self.env["x"].search_count([("m", "=", move.id)])
""",
    )
    assert [f.kind for f in found] == ["search_count"]


@pytest.mark.parametrize(
    ("label", "body"),
    [
        (
            "a boolean, not a counter field",
            """            if len(move.suitable_journal_ids) > 1:
                move.flag = True""",
        ),
        (
            "an index bound",
            """            i = 0
            if i == len(self.line_ids) - 1:
                move.flag = True""",
        ),
        (
            "a ratio numerator bound to a local, not to a field",
            """            done = len(move.completion_ids)
            move.ratio = done / 2""",
        ),
    ],
)
def test_a_len_that_is_not_a_counter_field_is_not_counted(tmp_path, label, body):
    source = f"""
class Move:
    def _compute_x(self):
        for move in self:
{body}
"""
    assert _count(tmp_path, source) == [], label


def test_a_len_under_a_newid_guard_is_not_counted(tmp_path):
    found = _count(
        tmp_path,
        """
class Task:
    def _compute_n(self):
        if not any(self._ids):
            for task in self:
                task.n = len(task.line_ids)
        else:
            for task in self:
                task.n = 0
""",
    )
    assert found == []


def test_a_newid_guard_does_not_excuse_the_other_branch(tmp_path):
    found = _count(
        tmp_path,
        """
class Task:
    def _compute_n(self):
        if not any(self._ids):
            for task in self:
                task.n = len(task.line_ids)
        for task in self:
            task.other = len(task.other_ids)
""",
    )
    assert [f.what for f in found] == ["_compute_n -> other_ids"]


def test_a_multi_hop_path_is_not_counted(tmp_path):
    found = _count(
        tmp_path,
        """
class Move:
    def _compute_n(self):
        for move in self:
            move.n = len(move.parent_id.line_ids)
""",
    )
    assert found == []


def test_counting_another_record_is_not_counted(tmp_path):
    found = _count(
        tmp_path,
        """
class Move:
    def _compute_n(self):
        for move in self:
            for other in move.others:
                move.n = len(other.line_ids)
""",
    )
    assert found == []


def test_a_field_not_named_with_the_relational_suffix_is_not_counted(tmp_path):
    found = _count(
        tmp_path,
        """
class Move:
    def _compute_n(self):
        for move in self:
            move.n = len(move.lines)
""",
    )
    assert found == []


def test_only_compute_methods_are_scanned(tmp_path):
    found = _count(
        tmp_path,
        """
class Move:
    def action_do(self):
        for move in self:
            move.n = len(move.line_ids)
""",
    )
    assert found == []


def test_a_read_group_compute_is_left_alone(tmp_path):
    found = _count(
        tmp_path,
        """
class Move:
    def _compute_n(self):
        data = self.env["l"]._read_group([("m", "in", self.ids)], ["m"], ["__count"])
        counts = dict(data)
        for move in self:
            move.n = counts.get(move.id, 0)
""",
    )
    assert found == []


def test_search_count_outside_a_loop_over_self_is_not_counted(tmp_path):
    found = _count(
        tmp_path,
        """
class Move:
    def _compute_n(self):
        total = self.env["l"].search_count([("m", "in", self.ids)])
        for move in self:
            move.n = total
""",
    )
    assert found == []


def test_an_ungoverned_addon_is_refused_rather_than_measured():
    assert gate.main(["--addon", "not_a_governed_scope", "--count"]) == 2


def test_every_governed_scope_resolves_to_a_path():
    for addon in gate.GOVERNED_ADDONS:
        assert isinstance(gate.addon_src(addon), Path)


def test_a_sibling_scope_skips_rather_than_reporting_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "SIBLING_SCOPES", ("enterprise",))
    monkeypatch.setattr(gate, "addon_src", lambda addon="core": tmp_path / "absent")
    assert gate.main(["--addon", "enterprise", "--count"]) == 0


def test_an_empty_scan_refuses_instead_of_reporting_zero(tmp_path):
    with pytest.raises(RuntimeError, match="no Python sources"):
        gate.measure(src=tmp_path)
