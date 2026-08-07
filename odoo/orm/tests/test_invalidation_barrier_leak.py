from collections import defaultdict

import pytest

from odoo.orm.components.model_graph import ModelGraph


def _publish(graph, triggers=None):
    start_epoch = graph.trigger_epoch
    return graph.set_triggers(triggers or defaultdict(dict), epoch=start_epoch)


def test_publication_works_when_no_teardown_is_open():
    graph = ModelGraph()
    assert _publish(graph) is True


def test_barrier_blocks_publication_while_open():
    graph = ModelGraph()
    graph.begin_invalidation()
    assert _publish(graph) is False, "an open teardown window must refuse"
    graph.end_invalidation()
    assert _publish(graph) is True, "and must accept again once closed"


def test_a_raising_teardown_leaves_the_barrier_open():
    graph = ModelGraph()

    with pytest.raises(TypeError):
        graph.begin_invalidation()
        raise TypeError("simulated malformed model")

    assert _publish(graph) is False
    assert _publish(graph) is False


def _functions_opening_a_teardown_window():
    import ast
    import pathlib

    orm_dir = pathlib.Path(__file__).resolve().parent.parent
    found = []
    for path in orm_dir.rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            opens = any(
                isinstance(c.func, ast.Attribute)
                and c.func.attr == "begin_invalidation"
                for c in ast.walk(node)
                if isinstance(c, ast.Call)
            )
            if opens:
                found.append((path.relative_to(orm_dir.parent), node))
    return found


def _closes_in_a_finally(func_node):
    import ast

    for node in ast.walk(func_node):
        if not isinstance(node, ast.Try):
            continue
        for stmt in node.finalbody:
            for call in ast.walk(stmt):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "end_invalidation"
                ):
                    return True
    return False


def test_the_scan_finds_the_real_call_sites():
    openers = _functions_opening_a_teardown_window()
    assert openers, "no begin_invalidation() call sites found -- scan is broken"


def test_every_teardown_window_is_closed_in_a_finally():
    leaking = [
        f"{path}::{node.name}"
        for path, node in _functions_opening_a_teardown_window()
        if not _closes_in_a_finally(node)
    ]
    assert not leaking, (
        "begin_invalidation() without a finally that ends it: " + ", ".join(leaking)
    )
