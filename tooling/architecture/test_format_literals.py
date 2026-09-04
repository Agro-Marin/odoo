from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import format_literals as gate

# The floor lives here rather than in `tooling/ratchet/baselines/`, because a
# baseline there is a promise that something drives it and this gate has no
# invocation of its own. It blocks through `pytest tooling/architecture/`,
# as the four other checkers `gates.md` names outside the table do, and none of
# them carries a baseline either.
FLOOR = 25

REGISTRATION = """
from odoo.libs.documents import Format, register_format

register_format(
    Format(mimetype="text/csv", extension="csv", representation="rows")
)
"""


def _tree(tmp_path: Path, source: str) -> list[gate.Finding]:
    (tmp_path / "formats.py").write_text(REGISTRATION, encoding="utf-8")
    (tmp_path / "consumer.py").write_text(source, encoding="utf-8")
    return gate.measure([tmp_path])


def test_deciding_both_facts_in_one_function_is_found(tmp_path):
    found = _tree(
        tmp_path,
        """
def export(self):
    return self._respond(
        content_type="text/csv",
        filename=f"{self.name}.csv",
    )
""",
    )
    assert [(f.scope, f.mimetype, f.extension) for f in found] == [
        ("export", "text/csv", "csv")
    ]


def test_a_bare_extension_counts_as_the_second_fact(tmp_path):
    found = _tree(
        tmp_path,
        """
def export(self):
    self.mimetype = "text/csv"
    self.file_type = "csv"
""",
    )
    assert len(found) == 1


def test_a_mimetype_alone_is_not_a_finding(tmp_path):
    # An `Accept:` or `Content-Type:` header names a protocol, not a file. The
    # first version of this gate counted those and answered 129 instead of 36.
    found = _tree(
        tmp_path,
        """
def fetch(self):
    return requests.get(url, headers={"Accept": "text/csv"})
""",
    )
    assert found == []


def test_an_extension_alone_is_not_a_finding(tmp_path):
    found = _tree(
        tmp_path,
        """
def export(self):
    return f"{self.name}.csv"
""",
    )
    assert found == []


def test_two_unrelated_functions_are_not_restating_each_other(tmp_path):
    found = _tree(
        tmp_path,
        """
def send(self):
    return {"Content-Type": "text/csv"}


def name(self):
    return "report.csv"
""",
    )
    assert found == []


def test_the_registration_itself_is_not_a_finding(tmp_path):
    (tmp_path / "formats.py").write_text(REGISTRATION, encoding="utf-8")
    assert gate.measure([tmp_path]) == []


def test_a_reader_or_writer_registration_is_not_a_finding(tmp_path):
    # `_writer("csv", "text/csv", ...)` names the writer `csv`; that is an
    # identifier, not a filename extension. Reading it as one made
    # `libs/documents/readers.py` and `writers.py` six of the gate's own
    # findings -- the declaration layer reported as its worst offender.
    (tmp_path / "formats.py").write_text(REGISTRATION, encoding="utf-8")
    (tmp_path / "consumer.py").write_text(
        """
register_writer(_writer("csv", "text/csv", ROWS, _write_csv))
register_reader(_reader("csv", {"text/csv"}, ("rows",), _read_csv))
""",
        encoding="utf-8",
    )
    assert gate.measure([tmp_path]) == []


def test_an_unregistered_format_is_invisible(tmp_path):
    found = _tree(
        tmp_path,
        """
def export(self):
    return ("application/pdf", f"{self.name}.pdf")
""",
    )
    assert found == []


def test_a_tree_declaring_no_format_refuses_rather_than_reporting_none(tmp_path):
    (tmp_path / "consumer.py").write_text(
        'X = "text/csv"\nY = "a.csv"\n', encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="measuring nothing"):
        gate.measure([tmp_path])


def test_the_extension_match_does_not_reach_into_a_mimetype(tmp_path):
    assert gate._names_the_extension(".csv", "csv")
    assert gate._names_the_extension("csv", "csv")
    assert gate._names_the_extension("report.csv", "csv")
    assert not gate._names_the_extension("text/csv", "csv")
    assert not gate._names_the_extension("csvish", "csv")


def test_the_live_tree_matches_the_committed_floor():
    # Two-sided on purpose, as an exact ratchet is: a fix that lowers the count
    # without lowering FLOOR fails here too, so the improvement gets banked
    # rather than leaving room to slip back.
    found = gate.measure([gate.ROOT / "odoo", gate.ROOT / "addons"])
    assert len(found) == FLOOR, (
        f"format literals moved: {len(found)} against a floor of {FLOOR}. "
        f"Each one closes by asking `mimetype_for(extension)` or "
        f"`extension_for(mimetype)` instead of stating the second fact; when you "
        f"have closed some, set FLOOR to {len(found)} in the same commit."
    )
