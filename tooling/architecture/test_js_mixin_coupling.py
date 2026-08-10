"""Tests for the JS mixin-coupling gate.

Two kinds, following ``test_js_private_access.py``. The behavioural tests build
synthetic mixin trees, so the suite does not change meaning as the real
composition is untangled. The tests that read the real tree assert only what a
measurement gate can silently lose: that it found its inputs, and that the
metrics it separates stay separated.
"""

import json
import pathlib
import subprocess
import sys

import doc_measured
import js_mixin_coupling as jmc  # sys.path set by conftest.py
import pytest

NODE_AVAILABLE = (
    subprocess.run(["node", "--version"], capture_output=True, check=False).returncode
    == 0
)
needs_node = pytest.mark.skipif(not NODE_AVAILABLE, reason="node is not on PATH")


def _analyse(tmp_path, files):
    """Run the real analyzer over a synthetic tree, returning {name: Unit}."""
    paths = []
    for name, source in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        paths.append(path)
    proc = subprocess.run(
        ["node", str(jmc.ANALYZER), *[str(p) for p in paths]],
        capture_output=True,
        text=True,
        check=True,
    )
    out = {}
    for line in proc.stdout.splitlines():
        raw = json.loads(line)
        out[pathlib.Path(raw["file"]).name] = raw
    return out


MIXIN = """
export const AMixin = (Base) =>
    class extends Base {
        defA() {
            return this.defB();
        }
    };
"""


# --- analyzer -------------------------------------------------------------


@needs_node
def test_defines_and_uses_are_collected_from_a_mixin_factory(tmp_path):
    got = _analyse(tmp_path, {"a.js": MIXIN})["a.js"]
    assert got["defines"] == ["defA"]
    assert got["uses"] == ["defB"]


@needs_node
def test_this_inside_a_nested_arrow_still_belongs_to_the_method(tmp_path):
    src = """
    export const M = (Base) => class extends Base {
        go() { [1].forEach(() => this.inner()); }
    };
    """
    assert _analyse(tmp_path, {"a.js": src})["a.js"]["uses"] == ["inner"]


@needs_node
def test_this_inside_a_nested_function_is_a_different_object(tmp_path):
    # The reason this is parsed and not regexed. A brace-counting collector
    # cannot tell these two `this` apart, and would invent an edge to `inner`.
    src = """
    export const M = (Base) => class extends Base {
        go() { (function () { return this.inner; })(); }
    };
    """
    assert _analyse(tmp_path, {"a.js": src})["a.js"]["uses"] == []


@needs_node
def test_computed_member_is_reported_as_dynamic_not_as_a_name(tmp_path):
    src = """
    export const M = (Base) => class extends Base {
        go(k) { return this[k]; }
    };
    """
    got = _analyse(tmp_path, {"a.js": src})["a.js"]
    assert got["uses"] == []
    assert got["dynamic"] == 1


@needs_node
def test_computed_key_does_not_become_a_definition(tmp_path):
    src = """
    const S = Symbol("s");
    export const M = (Base) => class extends Base { [S]() {} named() {} };
    """
    assert _analyse(tmp_path, {"a.js": src})["a.js"]["defines"] == ["named"]


@needs_node
def test_getters_and_fields_count_as_definitions(tmp_path):
    src = """
    export const M = (Base) => class extends Base {
        field = 1;
        get prop() { return 2; }
        set prop(v) {}
    };
    """
    assert _analyse(tmp_path, {"a.js": src})["a.js"]["defines"] == ["field", "prop"]


# --- graph ----------------------------------------------------------------


def _units(spec):
    return {
        name: jmc.Unit(module=name, defines=set(d), uses=set(u))
        for name, (d, u) in spec.items()
    }


def test_edge_exists_when_one_unit_uses_what_another_defines():
    units = _units({"a.js": (["x"], ["y"]), "b.js": (["y"], [])})
    assert jmc.build_edges(units) == {("a.js", "b.js")}


def test_a_unit_using_its_own_member_creates_no_edge():
    units = _units({"a.js": (["x"], ["x"]), "b.js": (["y"], [])})
    assert jmc.build_edges(units) == set()


def test_mutual_use_is_one_component_and_two_cyclic_edges():
    units = _units({"a.js": (["x"], ["y"]), "b.js": (["y"], ["x"])})
    edges = jmc.build_edges(units)
    components = jmc.strongly_connected(sorted(units), edges)
    assert max(len(c) for c in components) == 2
    assert len(jmc.cyclic_edges(edges, components)) == 2


def test_a_chain_is_acyclic():
    units = _units({"a.js": ([], ["y"]), "b.js": (["y"], ["z"]), "c.js": (["z"], [])})
    edges = jmc.build_edges(units)
    components = jmc.strongly_connected(sorted(units), edges)
    assert max(len(c) for c in components) == 1
    assert jmc.cyclic_edges(edges, components) == set()


def test_a_self_loop_is_not_a_cycle_of_two():
    # A single node is its own SCC; `cyclic_edges` must not count an edge as
    # cyclic just because both ends map to the same component of size 1.
    units = _units({"a.js": (["x"], ["x"])})
    edges = jmc.build_edges(units)
    components = jmc.strongly_connected(sorted(units), edges)
    assert jmc.cyclic_edges(edges, components) == set()


def test_shared_privates_needs_two_users_and_a_foreign_definition():
    units = _units(
        {
            "owner.js": (["_p"], []),
            "a.js": ([], ["_p"]),
            "b.js": ([], ["_p"]),
            "c.js": ([], ["_q"]),
        }
    )
    shared = jmc.shared_privates(units)
    assert list(shared) == ["_p"]
    assert shared["_p"] == ["a.js", "b.js"]


def test_public_names_are_not_shared_privates():
    units = _units({"owner.js": (["p"], []), "a.js": ([], ["p"]), "b.js": ([], ["p"])})
    assert jmc.shared_privates(units) == {}


# --- the real tree --------------------------------------------------------


@needs_node
def test_real_composition_is_scanned():
    # The empty-tree refusal every gate here ships: a gate that measured nothing
    # must not report a pass. COMPOSITIONS is enumerated, so the way this breaks
    # is a rename, and `analyse` exits rather than returning {}.
    assert jmc.modules(), "COMPOSITIONS is empty"
    state = jmc.measure()
    assert len(state["nodes"]) == len(jmc.modules())
    assert state["metrics"]["foreign"] > 0


@needs_node
def test_renamed_module_fails_loudly_rather_than_shrinking_the_graph():
    original = dict(jmc.COMPOSITIONS)
    try:
        jmc.COMPOSITIONS.clear()
        jmc.COMPOSITIONS["search/search_model.js"] = ["search/does_not_exist.js"]
        with pytest.raises(SystemExit):
            jmc.analyse(jmc.modules())
    finally:
        jmc.COMPOSITIONS.clear()
        jmc.COMPOSITIONS.update(original)


@needs_node
def test_baseline_matches_the_tree():
    assert jmc.measure()["metrics"] == jmc.BASELINE


@needs_node
def test_module_docstring_measured_block_is_fresh():
    problems = doc_measured.check(
        pathlib.Path(jmc.__file__), jmc.doc_metrics(jmc.measure())
    )
    assert not problems, (
        "stale MEASURED block:\n  "
        + "\n  ".join(problems)
        + ("\n\n  python tooling/architecture/js_mixin_coupling.py --update-doc")
    )


@needs_node
def test_check_passes_at_the_baseline():
    assert jmc.main(["--check"]) == 0


@needs_node
def test_check_fails_when_the_graph_grows(monkeypatch):
    monkeypatch.setitem(jmc.BASELINE, "max_scc", jmc.BASELINE["max_scc"] - 1)
    assert jmc.main(["--check"]) == 1


@needs_node
def test_check_fails_on_an_unlocked_improvement(monkeypatch):
    # Exact mode: getting better without lowering BASELINE fails too, so the
    # improvement is locked in rather than available to be re-spent.
    monkeypatch.setitem(jmc.BASELINE, "foreign", jmc.BASELINE["foreign"] + 10)
    assert jmc.main(["--check"]) == 1


# --- object-literal mixins ------------------------------------------------


OBJECT_MIXIN = """
export const fooMixin = {
    isNumeric(column) {
        return this.fields[column].type === "integer";
    },
    get rowCount() {
        return this.props.list.count;
    },
    ignored: () => this.notMine,
};
"""


@needs_node
def test_an_object_literal_mixin_is_measured(tmp_path):
    """THE regression: these reported empty, so enumerating the composition
    they belong to would have pinned a vacuous zero."""
    out = _analyse(tmp_path, {"m.js": OBJECT_MIXIN})["m.js"]
    assert out["classes"] == ["fooMixin"]
    assert set(out["defines"]) == {"isNumeric", "rowCount", "ignored"}
    assert {"fields", "props"} <= set(out["uses"])


@needs_node
def test_an_arrow_property_this_is_not_the_prototype(tmp_path):
    """An arrow's `this` is the module scope, not the object it is merged onto,
    so its reads say nothing about the composition."""
    out = _analyse(tmp_path, {"m.js": OBJECT_MIXIN})["m.js"]
    assert "notMine" not in out["uses"]


@needs_node
def test_a_non_mixin_object_literal_is_not_a_unit(tmp_path):
    """Matched by the `Mixin` suffix; every object literal is not a mixin."""
    source = "export const options = { a() { return this.b; } };\n"
    out = _analyse(tmp_path, {"m.js": source})["m.js"]
    assert out["classes"] == [] and out["defines"] == [] and out["uses"] == []


@needs_node
def test_the_three_list_renderer_mixins_are_all_seen(tmp_path):
    """Not synthetic: the live modules the composition entry names."""
    units = jmc.analyse(jmc.modules())
    for module in jmc.COMPOSITIONS["views/list/list_renderer.js"]:
        assert units[module].defines, f"{module} contributed no defines"
        assert units[module].uses, f"{module} contributed no uses"


# --- per-composition scoping ----------------------------------------------


def test_two_compositions_sharing_a_member_name_get_no_edge():
    """`fields`, `props` and `state` are defined in both live compositions; a
    flat pass over every pair invents an edge out of the shared name alone."""
    units = _units(
        {
            "one/base.js": (["fields"], []),
            "one/mix.js": ([], ["fields"]),
            "two/base.js": (["fields"], []),
            "two/mix.js": ([], ["fields"]),
        }
    )
    compositions = {"one/base.js": ["one/mix.js"], "two/base.js": ["two/mix.js"]}
    assert jmc.build_edges(units, compositions) == {
        ("one/mix.js", "one/base.js"),
        ("two/mix.js", "two/base.js"),
    }


def test_a_private_shared_only_by_name_across_compositions_is_not_shared():
    units = _units(
        {
            "one/base.js": (["_seen"], []),
            "one/mix.js": ([], ["_seen"]),
            "two/base.js": (["_seen"], []),
            "two/mix.js": ([], ["_seen"]),
        }
    )
    compositions = {"one/base.js": ["one/mix.js"], "two/base.js": ["two/mix.js"]}
    # One user per composition, so neither reaches the >=2 threshold.
    assert jmc.shared_privates(units, compositions) == {}


def test_every_declared_composition_module_is_on_disk():
    for base, mixins in jmc.COMPOSITIONS.items():
        for module in (base, *mixins):
            assert (jmc.WEB_SRC / module).is_file(), module


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
