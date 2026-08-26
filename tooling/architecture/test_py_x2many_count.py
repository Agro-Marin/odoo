"""What the counter gate counts, and — mostly — what it refuses to.

Eight floors rest on this one matcher, more than any other gate here, and it had
no test. That is the failure this whole directory exists to prevent: a matcher
that quietly widens moves eight numbers at once, and the first symptom is somebody
banking a floor that describes a bug rather than a tree.

THE EXCLUSIONS ARE THE VALUABLE PART. The module docstring records that each was
added after reading the sites rather than the number — a `len()` that is not a
counter, one under a `NewId` guard, one over a multi-hop path — and that counting
them "inflated the floor with code that has no fix", which is how a gate comes to
be read as broken and ignored. Nothing held any of them. Every paragraph of that
docstring is a case below.
"""

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


# --------------------------------------------------------------------------
# What it counts
# --------------------------------------------------------------------------


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
    assert [(f.kind, f.what) for f in found] == [("len", "_compute_lines_count -> line_ids")]


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


# --------------------------------------------------------------------------
# What it refuses, one case per paragraph of the docstring
# --------------------------------------------------------------------------


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
    """`fields.Count` replaces a counter FIELD and can express nothing else.

    So the `len()` has to be the entire right-hand side of an assignment to a
    field on the record being looped over. Counting these three put code with no
    available fix into the floor.
    """
    source = f"""
class Move:
    def _compute_x(self):
        for move in self:
{body}
"""
    assert _count(tmp_path, source) == [], label


def test_a_len_under_a_newid_guard_is_not_counted(tmp_path):
    """`fields.Count` falls back to `len()` for an unsaved record itself.

    A compute that already branches on `self._ids` and uses `len()` only there is
    the CORRECT shape, not the one this gate exists to remove — three sites in
    `addons/project/models/project_task.py` are exactly this.
    """
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
    """The guard covers what it encloses, and no more.

    Written because the flag is carried down an explicit walk of ANCESTORS
    rather than a flat `ast.walk`, and a walk that got the scoping wrong would
    silence the whole method instead of one branch — which is a hole, not a
    false positive.
    """
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
    """`len(record.parent_id.line_ids)` is not a field on this record.

    `fields.Count` cannot express it, so it is out of scope rather than debt.
    """
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
    """`a.n = len(b.line_ids)` counts b's lines onto a.

    Both halves must name the same record, or the declaration cannot replace it.
    """
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
    """The `_ids` suffix is load-bearing, and the docstring says so.

    `coding_guidelines.rst` fixes `_ids` for relational fields, so a name ending
    that way is a relation by the fork's own rule. Resolving the field properly
    would mean following `_inherit` across files; a ratchet wants a definition
    that is stable and cheap to re-derive. A counter over a field named otherwise
    is MISSED, and that is the trade — pinned here so it stays a trade rather
    than becoming a surprise.
    """
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
    """Correct as written; the gate must not push anyone off it."""
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
    """One query for the whole set is not the defect; one per record is."""
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


# --------------------------------------------------------------------------
# The scope machinery the eight floors depend on
# --------------------------------------------------------------------------


def test_an_ungoverned_addon_is_refused_rather_than_measured():
    """A floor over an unscanned tree checks nothing while looking like it does."""
    assert gate.main(["--addon", "not_a_governed_scope", "--count"]) == 2


def test_every_governed_scope_resolves_to_a_path():
    for addon in gate.GOVERNED_ADDONS:
        assert isinstance(gate.addon_src(addon), Path)


def test_a_sibling_scope_skips_rather_than_reporting_zero(monkeypatch, tmp_path):
    """Absent is not empty.

    A single-repo CI run cannot judge a sibling, and printing 0 would hand the
    ratchet a number that fails the floor while looking like the tree improved.
    """
    monkeypatch.setattr(gate, "SIBLING_SCOPES", ("enterprise",))
    monkeypatch.setattr(gate, "addon_src", lambda addon="core": tmp_path / "absent")
    assert gate.main(["--addon", "enterprise", "--count"]) == 0


def test_an_empty_scan_refuses_instead_of_reporting_zero(tmp_path):
    """Finding no sources is not the same as finding nothing wrong."""
    with pytest.raises(RuntimeError, match="no Python sources"):
        gate.measure(src=tmp_path)
