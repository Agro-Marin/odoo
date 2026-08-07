"""``odoo.libs``'s convenience facade must stay lazy (PEP 562).

It used to re-export eagerly, so importing *any* libs symbol -- or any area,
since the parent package runs first -- executed `.text`, which imports
`libs/text/html.py` and with it `lxml`, `lxml.html.clean`, `markupsafe` and
`arabic_reshaper`. Measured at the time of the change, in a fresh interpreter:

    from odoo.libs.collections import Collector     # a ~30-line helper
      eager facade:  131 modules, lxml + markupsafe loaded
      lazy  facade:   61 modules, no heavy third party

`odoo.libs` is the dependency-free layer and is imported from nearly everywhere,
so that cost was paid by consumers that never touch HTML.

These run in a subprocess because the assertion is about what a *fresh*
interpreter loads; inside the test session `lxml` is long since imported by
something else, and `sys.modules` cannot answer the question.
"""

import subprocess
import sys
import textwrap

_HEAVY = ("lxml", "markupsafe", "arabic_reshaper")


def _modules_after(code: str) -> set[str]:
    """Top-level module names loaded by ``code`` in a fresh interpreter."""
    script = textwrap.dedent(f"""
        import sys
        {code}
        print(" ".join(sorted({{m.split(".")[0] for m in sys.modules}})))
    """)
    out = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return set(out.stdout.split())


def test_importing_the_facade_does_not_pull_the_html_stack():
    loaded = _modules_after("import odoo.libs")
    heavy = sorted(set(_HEAVY) & loaded)
    assert not heavy, (
        f"`import odoo.libs` now loads {heavy}. The facade has gone eager again "
        "-- every consumer of the dependency-free layer pays for the HTML "
        "sanitiser. Keep the re-exports behind the module __getattr__."
    )


def test_importing_an_area_does_not_pull_the_html_stack():
    """Importing an area runs the parent package first -- that is the real path."""
    loaded = _modules_after("from odoo.libs.collections import Collector")
    heavy = sorted(set(_HEAVY) & loaded)
    assert not heavy, f"`from odoo.libs.collections import ...` now loads {heavy}"


def test_the_text_area_is_still_reachable_and_still_the_heavy_one():
    """The laziness must not have removed the names, only deferred them.

    The second half is the control: if `.text` stopped pulling the HTML stack,
    this whole test module is measuring nothing and should be re-derived.
    """
    loaded = _modules_after("from odoo.libs import human_size; human_size(1)")
    assert "odoo" in loaded
    heavy_on_demand = _modules_after("import odoo.libs.text")
    assert set(_HEAVY) & heavy_on_demand, (
        "odoo.libs.text no longer imports the HTML stack, so the laziness above "
        "proves nothing -- re-measure and rewrite these tests."
    )


def test_all_matches_the_export_table():
    """The literal `__all__` and the `_AREA_OF` table `__getattr__` reads.

    `__all__` is spelled out so static tools can see it, which means it can
    drift from the table that actually resolves the names. This is the guard
    that makes the duplication safe.
    """
    from odoo import libs

    advertised, resolvable = set(libs.__all__), set(libs._AREA_OF)
    assert advertised == resolvable, (
        "__all__ and _EXPORTS disagree -- advertised but unresolvable: "
        f"{sorted(advertised - resolvable)}; resolvable but unadvertised: "
        f"{sorted(resolvable - advertised)}"
    )
    assert len(libs.__all__) == len(advertised), "__all__ has duplicates"


def test_every_advertised_name_resolves():
    """`__all__` is derived from the same table `__getattr__` reads.

    A name that is advertised but unresolvable would only fail at first use,
    which for a rarely-used helper could be a long time after the mistake.
    """
    from odoo import libs

    unresolved = []
    for name in libs.__all__:
        try:
            getattr(libs, name)
        except AttributeError:
            unresolved.append(name)
    assert unresolved == [], f"advertised but unresolvable: {unresolved}"


def test_unknown_attribute_still_raises_attribute_error():
    from odoo import libs

    try:
        libs.definitely_not_a_real_helper
    except AttributeError:
        return
    raise AssertionError("__getattr__ must raise AttributeError for unknown names")
