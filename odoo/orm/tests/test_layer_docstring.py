"""`odoo.orm.__doc__` must not contradict itself.

The docstring opens by claiming it "cannot disagree" with the layer gate. It
disagreed with ITSELF: `_protocols.py` was listed twice, once under Layer 0 and
once under "Seams (deliberately not in any layer)", 22 lines apart.

The gate that watches this docstring, `tooling/architecture/test_architecture_doc`,
could not see it. One of its checks splits on the Layer 0 heading and never
reads the other sections; the other asks only whether each member name appears
somewhere in the text, which a name listed twice satisfies twice over.

This is the self-consistency half, and it lives here because it needs nothing
outside `odoo/orm`. Comparing the docstring against
`tooling/architecture/_orm_layer_scope.SCOPE` would be the other half; that
belongs with the gate in `tooling/`, which is outside this package.
"""

import re

import odoo.orm

#: Any line of the module layout that names a module or subpackage.
_ENTRY = re.compile(r"^  (\w+\.py|\w+/)\s", re.MULTILINE)


def _layout() -> str:
    """The listing: everything from the first layer heading to the closing note.

    There is no single "Module layout:" heading here -- the listing is the run of
    `Layer N` / `Cross-cutting` / `Seams` sections -- so the block is bounded by
    the first heading and the sentence that follows the last one.
    """
    doc = odoo.orm.__doc__ or ""
    _, sep, tail = doc.partition("Layer 0 — Zero-dependency foundations:")
    assert sep, "the docstring no longer opens its listing with the Layer 0 heading"
    block, sentinel, _ = tail.partition("Import from the public API packages")
    assert sentinel, "the listing no longer ends where this gate looks"
    return block


def test_no_module_is_listed_twice():
    entries = _ENTRY.findall(_layout())
    duplicated = sorted({e for e in entries if entries.count(e) > 1})
    assert not duplicated, (
        f"{duplicated} listed more than once in odoo/orm/__init__.py's layout; "
        f"a module classified twice means one of the two classifications is wrong"
    )


def test_every_module_on_disk_is_listed_exactly_once():
    import pathlib

    pkg = pathlib.Path(odoo.orm.__file__).parent
    on_disk = {p.name for p in pkg.glob("*.py") if p.name != "__init__.py"}
    on_disk |= {
        f"{d.name}/"
        for d in pkg.iterdir()
        if (d / "__init__.py").is_file() and d.name != "tests"
    }
    entries = _ENTRY.findall(_layout())
    assert set(entries) == on_disk, (
        f"listed but absent: {sorted(set(entries) - on_disk)}; "
        f"on disk but unlisted: {sorted(on_disk - set(entries))}"
    )
