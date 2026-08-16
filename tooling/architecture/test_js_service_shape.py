import json
import subprocess
import sys
from pathlib import Path

import js_service_shape as jss
import pytest

HERE = Path(__file__).resolve().parent


def _tree(monkeypatch, tmp_path, files):
    for rel, body in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    monkeypatch.setattr(jss, "WEB_SRC", tmp_path)
    return jss.analyse(jss.iter_service_files(tmp_path))


REGISTER = 'registry.category("services").add("thing", thingService);'


def test_a_start_returning_an_object_literal_is_a_literal(monkeypatch, tmp_path):
    got = _tree(
        monkeypatch,
        tmp_path,
        {
            "svc.js": "export const thingService = {\n"
            "    start(env) {\n"
            "        function helper() { return 1; }\n"
            "        return { helper };\n"
            "    },\n"
            "};\n" + REGISTER
        },
    )
    assert [(s.service, s.shape) for s in got] == [("thing", "literal")]


def test_a_start_returning_a_new_expression_is_an_instance(monkeypatch, tmp_path):
    got = _tree(
        monkeypatch,
        tmp_path,
        {
            "svc.js": "class Thing {}\n"
            "export const thingService = {\n"
            "    start(env) { return new Thing(env); },\n"
            "};\n" + REGISTER
        },
    )
    assert [s.shape for s in got] == ["instance"]


def test_one_hop_through_a_local_factory_resolves(monkeypatch, tmp_path):
    got = _tree(
        monkeypatch,
        tmp_path,
        {
            "svc.js": "class Thing {}\n"
            "function makeThing(env) { return new Thing(env); }\n"
            "export const thingService = {\n"
            "    start(env) {\n"
            "        const t = makeThing(env);\n"
            "        t.extra = 1;\n"
            "        return t;\n"
            "    },\n"
            "};\n" + REGISTER
        },
    )
    assert [s.shape for s in got] == ["instance"]


def test_a_nested_functions_return_is_not_the_services(monkeypatch, tmp_path):
    got = _tree(
        monkeypatch,
        tmp_path,
        {
            "svc.js": "class Thing {}\n"
            "export const thingService = {\n"
            "    start(env) {\n"
            "        function helper() { return { a: 1 }; }\n"
            "        helper();\n"
            "        return new Thing();\n"
            "    },\n"
            "};\n" + REGISTER
        },
    )
    assert [s.shape for s in got] == ["instance"]


def test_an_unfollowable_return_is_unknown_not_literal(monkeypatch, tmp_path):
    got = _tree(
        monkeypatch,
        tmp_path,
        {
            "svc.js": 'import { build } from "./elsewhere";\n'
            "export const thingService = {\n"
            "    start(env) { return build(env); },\n"
            "};\n" + REGISTER
        },
    )
    assert [s.shape for s in got] == ["unknown"]


def test_only_literals_feed_the_budget(monkeypatch, tmp_path):
    got = _tree(
        monkeypatch,
        tmp_path,
        {
            "a.js": "export const thingService = { start() { return {}; } };\n"
            + REGISTER,
            "b.js": "class T {}\nexport const otherService = { start() { return new T(); } };\n"
            'registry.category("services").add("other", otherService);',
        },
    )
    assert len(got) == 2
    assert [s.service for s in jss.literals(got)] == ["thing"]


def test_a_service_registered_through_a_bound_category_is_seen(monkeypatch, tmp_path):

    got = _tree(
        monkeypatch,
        tmp_path,
        {
            "svc.js": 'const services = registry.category("services");\n'
            "export const thingService = { start() { return {}; } };\n"
            'services.add("thing", thingService);'
        },
    )
    assert [(s.service, s.shape) for s in got] == [("thing", "literal")]


def test_reactive_and_markraw_are_transparent(monkeypatch, tmp_path):

    got = _tree(
        monkeypatch,
        tmp_path,
        {
            "svc.js": 'import { reactive } from "@odoo/owl";\n'
            "export const thingService = {\n"
            "    start() {\n"
            "        const state = reactive({ a: 1 });\n"
            "        return state;\n"
            "    },\n"
            "};\n" + REGISTER
        },
    )
    assert [s.shape for s in got] == ["literal"]


def test_a_transparent_wrapper_around_an_instance_is_still_an_instance(
    monkeypatch, tmp_path
):
    got = _tree(
        monkeypatch,
        tmp_path,
        {
            "svc.js": 'import { markRaw } from "@odoo/owl";\n'
            "class Thing {}\n"
            "export const thingService = {\n"
            "    start() { return markRaw(new Thing()); },\n"
            "};\n" + REGISTER
        },
    )
    assert [s.shape for s in got] == ["instance"]


def test_a_file_registering_no_service_is_not_analysed(monkeypatch, tmp_path):
    got = _tree(
        monkeypatch,
        tmp_path,
        {"plain.js": "export const notAService = { start() { return {}; } };\n"},
    )
    assert got == []


def test_unparseable_source_is_skipped_not_crashed(monkeypatch, tmp_path):
    got = _tree(
        monkeypatch,
        tmp_path,
        {
            "broken.js": "export const thingService = { start( {{{ \n" + REGISTER,
            "ok.js": "export const okService = { start() { return {}; } };\n"
            'registry.category("services").add("ok", okService);',
        },
    )
    assert [s.service for s in got] == ["ok"]


def test_the_known_instance_shaped_services_are_detected():

    services = jss.analyse(jss.iter_service_files())
    instances = {s.service for s in services if s.shape == "instance"}
    assert {"action", "orm"} <= instances


def test_line_counts_agree_with_the_function_length_gate():

    services = {s.service: s.lines for s in jss.analyse(jss.iter_service_files())}
    out = subprocess.run(
        [sys.executable, str(HERE / "js_function_length.py"), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    by_file = {}
    for item in json.loads(out.stdout):
        if "'start'" in item["what"]:
            by_file[Path(item["file"]).name] = item["lines"]

    population = [
        s
        for s in jss.analyse(jss.iter_service_files())
        if s.shape == "literal" and s.lines > jss.LARGE
    ]
    if not population:
        pytest.skip("no oversized literal start() left — nothing to cross-check")

    checked = 0
    for svc in population:
        name = Path(svc.file).name
        if name not in by_file:
            continue
        assert abs(by_file[name] - services[svc.service]) <= 1, svc.service
        checked += 1
    assert checked == len(population), (
        f"cross-checked {checked} of {len(population)} oversized literal "
        "services; every one must appear in both tools, and a shortfall means "
        "they disagree about what a service's start() is"
    )


def test_the_budget_is_the_literal_count():
    services = jss.analyse(jss.iter_service_files())
    assert jss.main(["--count"]) == 0
    assert len(jss.literals(services)) == len(
        [s for s in services if s.shape == "literal"]
    )


def test_an_empty_tree_is_refused_rather_than_passed(monkeypatch, tmp_path):
    monkeypatch.setattr(jss, "WEB_SRC", tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        jss.main([])
    assert excinfo.value.code != 0
