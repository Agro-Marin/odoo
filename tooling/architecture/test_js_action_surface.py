"""Probes for the action-service surface gate.

`test_every_gate_refuses_an_empty_tree` proves this gate says something when it
is pointed at nothing. These prove it says the *right* thing when pointed at a
breach — and, just as importantly, that it stays quiet where a naive version of
it invented findings. The regression in the third test is not hypothetical: the
gate's first run over the real tree reported eight undeclared members, and all
eight were Controller members it had attributed to the service.
"""

import js_action_surface as jas
import pytest

SURFACE = frozenset({"doAction", "currentController", "env"})

CONTRACT_SRC = """// @ts-check
export const ACTION_MANAGER_SURFACE = [
    "doAction",
    "currentController",
    "env",
];
"""


# The real `odoo` scope carries an `addons/` level and the sibling repos do not,
# and ACTIONS_SUBTREE is spelled against the former. The fixture mirrors that
# rather than inventing a flat layout, so what the tests assert is what the gate
# sees in the tree it actually runs on.
ODOO_PREFIX = "addons/web/static/src"
SIBLING_PREFIX = "web/static/src"


@pytest.fixture
def tree(tmp_path):
    def write(rel, text, scope="odoo", prefix=ODOO_PREFIX):
        path = tmp_path / scope / prefix / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    write.roots = lambda *scopes: tuple(
        (scope, tmp_path / scope) for scope in (scopes or ("odoo",))
    )
    write.tmp = tmp_path
    return write


def _scan(tree, *scopes, surface=SURFACE, recorded=frozenset()):
    return jas.find_reaches(tree.roots(*scopes), surface=surface, recorded=recorded)


def test_the_contract_is_parsed_from_source_not_restated_here(tmp_path):
    contract = tmp_path / "action_service_contract.js"
    contract.write_text(CONTRACT_SRC, encoding="utf-8")
    assert jas.declared_surface(contract) == SURFACE


def test_an_undeclared_reach_through_env_services_is_caught(tree):
    tree("some/consumer.js", "env.services.action.loadState();\n")
    findings, scanned, scopes = _scan(tree)
    assert scanned == 1
    assert scopes == ["odoo"]
    assert [(f.member, f.line) for f in findings] == [("loadState", 1)]


def test_an_undeclared_reach_through_a_useService_binding_is_caught(tree):
    tree(
        "some/component.js",
        "setup() {\n"
        '    this.actionService = useService("action");\n'
        "}\n"
        "go() {\n"
        "    return this.actionService.loadAction(1);\n"
        "}\n",
    )
    findings, _, _ = _scan(tree)
    assert [(f.member, f.line) for f in findings] == [("loadAction", 5)]


def test_a_controller_bound_off_the_service_is_not_the_service(tree):
    # THE regression this gate shipped with, and the reason for the `(?!\\s*\\.)`
    # anchor: an unanchored receiver bound `currentController` as if it were the
    # manager, and every Controller member read through it became a finding.
    tree(
        "some/consumer.js",
        "const currentController = env.services.action.currentController;\n"
        "if (currentController.virtual) {\n"
        "    currentController.getLocalState();\n"
        "}\n",
    )
    findings, _, _ = _scan(tree)
    assert findings == [], f"invented surface: {[f.member for f in findings]}"


def test_a_declared_reach_is_silent(tree):
    tree("some/consumer.js", "env.services.action.doAction({});\n")
    assert _scan(tree)[0] == []


def test_tests_are_out_of_scope(tree):
    path = tree.tmp / "odoo" / "addons" / "web" / "static" / "tests" / "a.test.js"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("env.services.action.loadState();\n", encoding="utf-8")
    findings, scanned, _ = _scan(tree)
    assert findings == []
    assert scanned == 0, "a test tree must not even be counted as scanned"


def test_the_am_convention_applies_only_inside_the_actions_subtree(tree):
    body = "export function run(am) {\n    return am.loadState();\n}\n"
    tree("webclient/actions/executors/x.js", body)
    inside, _, _ = _scan(tree)
    assert [f.member for f in inside] == ["loadState"], (
        "inside actions/, `am` is the manager by convention"
    )

    other = tree.tmp / "other"
    elsewhere = other / SIBLING_PREFIX / "elsewhere"
    elsewhere.mkdir(parents=True)
    (elsewhere / "y.js").write_text(body, encoding="utf-8")
    outside, _, _ = jas.find_reaches(
        (("other", other),), surface=SURFACE, recorded=frozenset()
    )
    assert outside == [], (
        "outside actions/, `am` is any local and counting it invents members"
    )


def test_a_recorded_misreach_is_excused_but_only_where_recorded(tree):
    tree("some/consumer.js", "env.services.action.loadState();\n")
    recorded = frozenset({("odoo", f"{ODOO_PREFIX}/some/consumer.js", "loadState")})
    assert _scan(tree, recorded=recorded)[0] == []
    assert _scan(tree, recorded=frozenset())[0] != [], "control: it is caught unexcused"


def test_an_absent_sibling_scope_is_skipped_not_failed(tree):
    tree("some/consumer.js", "env.services.action.doAction({});\n")
    findings, scanned, scopes = jas.find_reaches(
        (("odoo", tree.tmp / "odoo"), ("enterprise", tree.tmp / "nope")),
        surface=SURFACE,
        recorded=frozenset(),
    )
    # CI checks this repo out alone; a missing sibling must not read as clean
    # coverage of it, so the scope list is what the report names.
    assert findings == []
    assert scanned == 1
    assert scopes == ["odoo"]
