import textwrap
from pathlib import Path

import pytest

from . import debuglog

CLEAN = textwrap.dedent(
    """
    import logging

    _logger = logging.getLogger(__name__)


    def work(records, cr):
        total = 0
        for record in records:
            total += record
        if total > 10:
            cr.execute("SELECT 1")
        return total
    """
).lstrip()

INSTRUMENTED = textwrap.dedent(
    """
    import logging

    from odoo.libs.debug_log import DebugLog

    _logger = logging.getLogger(__name__)
    _debug = DebugLog(__name__)


    def work(records, cr):
        total = 0
        seen = 0  # debuglog
        with _debug.perf("work", cr=cr, records=len(records)) as span:
            for record in records:
                total += record
                seen += 1  # debuglog
            span.set(total=total)
        if _debug.logic.enabled and total > 10:
            _debug.logic("work.large", total=total)
        if total > 10:
            _debug.pipeline("work.execute", total=total)
            cr.execute("SELECT 1")
        _debug.perf.count("work.done", total=total)
        _debug.lifecycle("work.end")
        return total
    """
).lstrip()


def _write(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(source)
    return path


def _check(tmp_path: Path, source: str) -> list[str]:
    path = _write(tmp_path, "mod.py", source)
    report = debuglog.scan_file(path)
    assert report is not None
    return [v.message for v in report.violations]


def test_every_documented_shape_passes_check(tmp_path):
    assert _check(tmp_path, INSTRUMENTED) == []


def test_strip_restores_the_clean_module(tmp_path):
    path = _write(tmp_path, "mod.py", INSTRUMENTED)
    report = debuglog.scan_file(path)
    assert report is not None
    stripped = debuglog.strip_file(report)
    assert stripped.split() == CLEAN.split()
    assert not debuglog._SURVIVOR_RE.search(stripped)


def test_list_counts_one_site_per_channel_kind(tmp_path):
    path = _write(tmp_path, "mod.py", INSTRUMENTED)
    report = debuglog.scan_file(path)
    assert report is not None
    kinds = sorted(site.kind for site in report.sites)
    assert kinds == sorted(
        [
            "import",
            "assignment",
            "span",
            "span_set",
            "guard",
            "line",
            "line",
            "line",
            "marker",
            "marker",
        ]
    )


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ("    _debug.perf('x')\n", "bare _debug.perf"),
        (
            "    with _debug.perf('x'), open('f') as f:\n        pass\n",
            "only item",
        ),
        (
            "    if _debug.logic.enabled:\n        pass\n    else:\n        pass\n",
            "no else",
        ),
        ("    if flag:\n        _debug.logic('x')\n", "only statement"),
        ("    value = _debug.perf('x')\n", "outside the strippable shapes"),
        ("    other = DebugLog('x')\n", "module-level"),
        ("    if _debug.logic.enabled:\n        total = 1\n", "debug lines and"),
    ],
)
def test_check_refuses_an_unstrippable_shape(tmp_path, body, fragment):
    source = (
        "from odoo.libs.debug_log import DebugLog\n"
        "_debug = DebugLog(__name__)\n"
        "flag = True\n"
        "def f():\n" + body + "    return 1\n"
    )
    messages = _check(tmp_path, source)
    assert any(fragment in message for message in messages), messages


def test_a_module_without_debug_references_is_skipped(tmp_path):
    path = _write(tmp_path, "mod.py", CLEAN)
    assert debuglog.scan_file(path) is None


def test_the_core_tree_passes_check():
    roots = [debuglog.REPO / "odoo" / d for d in ("orm", "db", "http", "service")]
    reports = debuglog.scan(roots)
    violations = [v for report in reports for v in report.violations]
    assert violations == []
