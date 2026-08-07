"""``begin_invalidation()`` must be closed even when model setup raises.

``Registry._setup_models__`` opens a teardown window with
``model_graph.begin_invalidation()`` and closes it with ``end_invalidation()``
~80 lines later.  Between the two sit ``registration.setup_model_classes(env)``
and the ``field.get_depends(model)`` loop, both of which raise on a malformed
model -- ``registration`` alone has five ``raise TypeError`` sites reachable
from a bad ``ir.model`` / ``ir.model.fields`` row.  There is no ``try/finally``,
so the window is left open.

While the barrier is up, ``ModelGraph.set_triggers`` refuses every
epoch-validated publication, and ``Registry._field_triggers`` -- the sole
epoch-validated publisher in the tree -- is a ``cached_property``, so the
refused (stale) result is memoized on the registry as well.

Scope, measured rather than assumed: this does **not** stop recomputation.  The
previously published snapshot stays in place and stays correct as long as the
model set has not actually changed, and a later *successful* ``_setup_models__``
calls ``end_invalidation()`` and republishes.  What the missing ``finally``
costs is that the registry is left in a state where trigger publication is
silently disabled until some other caller happens to complete a successful
setup -- a failure mode with no log line and no way for a reader to tell the
barrier is up.

Both tests use ``ModelGraph`` directly: the invariant belongs to the component,
and pinning it here keeps the suite database-free.
"""

from collections import defaultdict

import pytest

from odoo.orm.components.model_graph import ModelGraph


def _publish(graph, triggers=None):
    """Attempt an epoch-validated publication, as ``_field_triggers`` does."""
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
    """The shape of ``_setup_models__``: begin, raise, never end."""
    graph = ModelGraph()

    with pytest.raises(TypeError):
        graph.begin_invalidation()
        raise TypeError("simulated malformed model")

    assert _publish(graph) is False
    # ... and it stays refused for every later attempt, with nothing logged.
    assert _publish(graph) is False


def _functions_opening_a_teardown_window():
    """Every function in odoo/orm that calls ``begin_invalidation()``."""
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
    """Is ``end_invalidation()`` reached from some ``finally:`` in this function?"""
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
    """Guard the guard: if this ever returns nothing, the check below is vacuous."""
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
