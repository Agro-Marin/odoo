import json
import pathlib
import re
import subprocess
import sys

import doc_measured
import js_mixin_coupling as jmc
import pytest

NODE_AVAILABLE = (
    subprocess.run(["node", "--version"], capture_output=True, check=False).returncode
    == 0
)
needs_node = pytest.mark.skipif(not NODE_AVAILABLE, reason="node is not on PATH")


def _analyse(tmp_path, files):
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


@needs_node
def test_real_composition_is_scanned():
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
    monkeypatch.setitem(jmc.BASELINE, "foreign", jmc.BASELINE["foreign"] + 10)
    assert jmc.main(["--check"]) == 1


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
    out = _analyse(tmp_path, {"m.js": OBJECT_MIXIN})["m.js"]
    assert out["classes"] == ["fooMixin"]
    assert set(out["defines"]) == {"isNumeric", "rowCount", "ignored"}
    assert {"fields", "props"} <= set(out["uses"])


@needs_node
def test_an_arrow_property_this_is_not_the_prototype(tmp_path):
    out = _analyse(tmp_path, {"m.js": OBJECT_MIXIN})["m.js"]
    assert "notMine" not in out["uses"]


@needs_node
def test_a_non_mixin_object_literal_is_not_a_unit(tmp_path):
    source = "export const options = { a() { return this.b; } };\n"
    out = _analyse(tmp_path, {"m.js": source})["m.js"]
    assert out["classes"] == [] and out["defines"] == [] and out["uses"] == []


@needs_node
def test_the_three_list_renderer_mixins_are_all_seen(tmp_path):
    units = jmc.analyse(jmc.modules())
    for module in jmc.COMPOSITIONS["views/list/list_renderer.js"]:
        assert units[module].defines, f"{module} contributed no defines"
        assert units[module].uses, f"{module} contributed no uses"


def test_two_compositions_sharing_a_member_name_get_no_edge():
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
    assert jmc.shared_privates(units, compositions) == {}


def test_every_declared_composition_module_is_on_disk():
    for base, mixins in jmc.COMPOSITIONS.items():
        for module in (base, *mixins):
            assert (jmc.WEB_SRC / module).is_file(), module


def test_a_single_line_declaration_does_not_swallow_the_next_one():
    # Prettier collapses a one-element array onto a single line. A terminator
    # that assumes a multi-line array reads that as unterminated and runs on to
    # the NEXT array's close, merging two declarations -- a false pass, not a
    # crash, so it needs a test of its own.
    source = (
        'export const X_PUBLISHED = ["only"];\n'
        "\n"
        "export const X_REQUIRES = [\n"
        '    "first",\n'
        '    "second",\n'
        "];\n"
    )
    published = jmc._array_literal(source, "export const X_PUBLISHED = [")
    assert re.findall(r'"([^"]+)"', published) == ["only"]
    requires = jmc._array_literal(source, "export const X_REQUIRES = [")
    assert re.findall(r'"([^"]+)"', requires) == ["first", "second"]


def test_a_missing_declaration_is_none_rather_than_a_wrong_answer():
    assert jmc._array_literal("const other = [1];", "export const X_A = [") is None


def test_every_contract_file_and_its_covered_modules_are_on_disk():
    for contract, prefixes in jmc.CONTRACT_FILES.items():
        assert (jmc.WEB_SRC / contract).is_file(), contract
        for module in prefixes:
            assert (jmc.WEB_SRC / module).is_file(), module


def test_the_contract_covers_only_modules_the_gate_measures():
    measured = set(jmc.modules())
    for contract, prefixes in jmc.CONTRACT_FILES.items():
        unmeasured = sorted(set(prefixes) - measured)
        assert not unmeasured, f"{contract} declares unmeasured module(s): {unmeasured}"


def test_the_declared_contract_parses_to_three_non_empty_kinds():
    declared = jmc.declared_contracts()
    assert declared, "no contract parsed"
    for module, kinds in declared.items():
        assert set(kinds) == {"PUBLISHED", "REQUIRES", "SHARED_STATE"}, module
        assert any(kinds.values()), f"{module} declared nothing at all"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
