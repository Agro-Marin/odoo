"""The "Module layout" block of ``odoo.service.__doc__`` is checked by nothing.

It went stale exactly the way an unchecked list does: ``db.py`` became the
``db/`` package (ADR-0014) and the docstring kept describing it as one module,
while ``_metrics.py`` -- real surface, imported by
``addons/web/controllers/home.py`` to serve ``/web/metrics`` -- was never added
at all.  A reader who trusts the block goes looking for a file that is not
there and misses one that is.

This gate is the reason the block can be trusted from here on: it is derived
from the tree on every run, so the next module added to the package fails a
test instead of quietly widening the gap.
"""

import pathlib
import re

import odoo.service

#: ``    name.py         description`` or ``    db/             description``.
#: Nested entries (the ``db/`` submodules) are indented deeper and are matched
#: separately, so a top-level entry is exactly four spaces in.
_ENTRY = re.compile(r"^ {4}(\w+\.py|\w+/)\s+\S", re.MULTILINE)
_NESTED = re.compile(r"^ {8}(\w+\.py)\s+\S", re.MULTILINE)

PKG = pathlib.Path(odoo.service.__file__).parent


def _layout_block() -> str:
    doc = odoo.service.__doc__ or ""
    _, _, tail = doc.partition("Module layout:\n")
    assert tail, "the docstring no longer has a Module layout block"
    block, _, _ = tail.partition("\nSubmodules are imported eagerly")
    assert block, "the Module layout block no longer ends where this gate looks"
    return block


def _on_disk(directory: pathlib.Path) -> set[str]:
    return {p.name for p in directory.glob("*.py") if p.name != "__init__.py"}


def test_layout_lists_every_top_level_module_and_no_others():
    documented = set(_ENTRY.findall(_layout_block()))
    on_disk = _on_disk(PKG) | {
        f"{p.name}/" for p in PKG.iterdir() if (p / "__init__.py").is_file()
    }
    assert documented == on_disk, (
        f"documented but absent: {sorted(documented - on_disk)}; "
        f"on disk but undocumented: {sorted(on_disk - documented)}"
    )


def test_layout_lists_every_module_of_the_db_package():
    documented = set(_NESTED.findall(_layout_block()))
    assert documented == _on_disk(PKG / "db")
