import pathlib
import re

import odoo.service

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
