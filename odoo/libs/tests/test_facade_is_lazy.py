import json
import subprocess
import sys
import textwrap

_HEAVY = ("lxml", "markupsafe", "arabic_reshaper")


def _probe(code: str) -> str:
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _modules_after(code: str) -> set[str]:
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
    loaded = _modules_after("from odoo.libs.collections import Collector")
    heavy = sorted(set(_HEAVY) & loaded)
    assert not heavy, f"`from odoo.libs.collections import ...` now loads {heavy}"


def test_the_text_area_is_still_reachable_and_still_the_heavy_one():
    loaded = _modules_after("from odoo.libs import human_size; human_size(1)")
    assert "odoo" in loaded
    heavy_on_demand = _modules_after("import odoo.libs.text")
    assert set(_HEAVY) & heavy_on_demand, (
        "odoo.libs.text no longer imports the HTML stack, so the laziness above "
        "proves nothing -- re-measure and rewrite these tests."
    )


def test_all_matches_the_export_table():
    table = json.loads(_probe("""
        import json
        from odoo import libs
        print(json.dumps({
            "advertised": sorted(libs.__all__),
            "resolvable": sorted(libs._AREA_OF),
            "duplicated": len(libs.__all__) != len(set(libs.__all__)),
        }))
    """))
    advertised, resolvable = set(table["advertised"]), set(table["resolvable"])
    assert advertised == resolvable, (
        "__all__ and _EXPORTS disagree -- advertised but unresolvable: "
        f"{sorted(advertised - resolvable)}; resolvable but unadvertised: "
        f"{sorted(resolvable - advertised)}"
    )
    assert not table["duplicated"], "__all__ has duplicates"


def test_every_advertised_name_resolves():
    unresolved = json.loads(_probe("""
        import json
        from odoo import libs
        unresolved = []
        for name in libs.__all__:
            try:
                getattr(libs, name)
            except AttributeError:
                unresolved.append(name)
        print(json.dumps(unresolved))
    """))
    assert unresolved == [], f"advertised but unresolvable: {unresolved}"


def test_unknown_attribute_still_raises_attribute_error():
    raised = _probe("""
        from odoo import libs
        try:
            libs.definitely_not_a_real_helper
        except AttributeError:
            print("AttributeError")
        else:
            print("nothing")
    """)
    assert raised == "AttributeError", (
        "__getattr__ must raise AttributeError for unknown names, got: " + raised
    )
