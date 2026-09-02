from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import werkzeug_in_addons as gate


def _measure(tmp_path: Path, source: str) -> list[gate.ToolkitImport]:
    path = tmp_path / "addons" / "thing" / "controllers" / "main.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return gate.measure(files=[path])


def test_a_from_import_of_an_exception_is_found(tmp_path):
    found = _measure(tmp_path, "from werkzeug.exceptions import NotFound\n")
    assert [item.names for item in found] == [("werkzeug.exceptions.NotFound",)]


def test_a_bare_import_and_a_submodule_import_are_found(tmp_path):
    found = _measure(tmp_path, "import werkzeug\nimport werkzeug.routing\n")
    assert [item.names for item in found] == [("werkzeug", "werkzeug.routing")]


def test_a_function_body_import_counts(tmp_path):
    found = _measure(
        tmp_path,
        "def go():\n    from werkzeug.exceptions import abort\n    abort(404)\n",
    )
    assert len(found) == 1


def test_one_file_is_one_finding_however_many_statements(tmp_path):
    found = _measure(
        tmp_path,
        "import werkzeug.utils\nfrom werkzeug.exceptions import Forbidden, NotFound\n",
    )
    assert len(found) == 1
    assert found[0].names == (
        "werkzeug.utils",
        "werkzeug.exceptions.Forbidden",
        "werkzeug.exceptions.NotFound",
    )


def test_the_frameworks_vocabulary_is_not_a_finding(tmp_path):
    found = _measure(
        tmp_path,
        "from odoo.http import Forbidden, NotFound, request\n"
        "from werkzeugish import thing\n",
    )
    assert found == []


def test_test_files_are_out_of_scope(tmp_path):
    path = tmp_path / "addons" / "thing" / "tests" / "test_main.py"
    path.parent.mkdir(parents=True)
    path.write_text("from werkzeug.exceptions import NotFound\n", encoding="utf-8")
    assert gate.iter_source_files(tmp_path) == []


def test_an_empty_tree_is_refused(tmp_path):
    (tmp_path / "addons").mkdir()
    (tmp_path / "odoo" / "addons").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="found nothing"):
        gate.measure(src=tmp_path)


def test_the_real_tree_has_findings_and_a_summary_by_name():
    found = gate.measure()
    assert found, "the bundled addons import werkzeug nowhere -- the scan is broken"
    assert "by name:" in gate._summary(found)
