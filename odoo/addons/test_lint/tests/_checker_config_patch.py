import ast
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass
class Violation:
    lineno: int
    col_offset: int
    message: str = ""


def _is_patch_dict(func: ast.expr) -> bool:
    """``patch.dict`` / ``mock.patch.dict`` / ``unittest.mock.patch.dict``."""
    match func:
        case ast.Attribute(attr="dict", value=ast.Name(id="patch")):
            return True
        case ast.Attribute(attr="dict", value=ast.Attribute(attr="patch")):
            return True
    return False


def _is_config_options(node: ast.expr) -> bool:
    """``config.options`` however it was reached — the attribute chain is free.

    ``tools.config.options``, ``odoo.tools.config.options`` and
    ``db_mod.lifecycle.odoo.tools.config.options`` are all the same object.
    """
    match node:
        case ast.Attribute(attr="options", value=ast.Name(id="config")):
            return True
        case ast.Attribute(attr="options", value=ast.Attribute(attr="config")):
            return True
    return False


def check(tree: ast.Module, nodes=None) -> Iterator[Violation]:
    """Report ``patch.dict`` applied to ``config.options``.

    ``config.options`` is a ``ChainMap`` over six layers. ``patch.dict`` restores
    by ``clear()`` then ``update()``, and on a ChainMap ``clear()`` empties only
    ``maps[0]`` while ``update()`` writes the *flattened* mapping back into it —
    so every lower layer ends up pinned in the top one:

        a, b = {}, {"x": 1}
        cm = collections.ChainMap(a, b)
        with patch.dict(cm, {"x": 99}):
            pass
        a  # -> {'x': 1}

    ``maps[0]`` is ``_override_options``, so after one such patch it shadows
    everything and any later write to a lower layer is silently ignored. The
    damage lands on whichever test runs next, which is why this is a lint rule
    and not something the next reviewer is expected to spot.

    ``config.patch(**values)`` exists for this and touches only the keys named.
    """
    for node in nodes if nodes is not None else ast.walk(tree):
        match node:
            case ast.Call(func=func, args=[first, *_]) if _is_patch_dict(
                func
            ) and _is_config_options(first):
                yield Violation(
                    node.lineno,
                    node.col_offset,
                    "use config.patch(**values) — patch.dict flattens the "
                    "options ChainMap into _override_options",
                )
