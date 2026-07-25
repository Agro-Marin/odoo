"""Differential parity for the ``origin_ids`` accelerator.

Tier-2 suite (real ``import odoo``, no database — run as ``pytest
odoo/orm/tests``).

``odoo.orm.helpers._origin_ids`` dispatches on the argument type: tuples go to
the Rust ``odoo_rust.origin_ids``, every other iterable to the Python
``_origin_ids_python``.  Both are live production paths, so a divergence is a
real bug — a recordset's origin ids would depend on whether the caller happened
to hold a tuple.  Nothing tested the pair before.

The contract, per element: a truthy id is kept as-is; a falsy one contributes
its ``origin`` when that is truthy; anything else is dropped.  Only
``AttributeError`` is swallowed while reading ``origin`` — matching
``getattr(id_, "origin", None)`` — so an exploding ``__getattr__`` must
propagate identically from both.
"""

import pytest
from odoo_rust import origin_ids as origin_ids_rust  # type: ignore[import-untyped]

from odoo.orm.helpers import _origin_ids, _origin_ids_python
from odoo.orm.primitives import NewId


class _NoOrigin:
    """Falsy, and has no ``origin`` attribute at all."""

    def __bool__(self) -> bool:
        return False


class _RaisingOrigin:
    """Falsy, and reading ``origin`` raises something other than AttributeError."""

    def __bool__(self) -> bool:
        return False

    def __getattr__(self, name: str):
        raise RuntimeError(f"boom: {name}")


CASES = [
    (),
    (1, 2, 3),
    (0,),
    (False,),
    (None,),
    (NewId(),),
    (NewId(5),),
    (NewId(0),),  # falsy origin -> dropped
    (NewId(-3),),  # truthy negative origin -> kept
    (1, NewId(2), 0, NewId(), 3),
    (NewId(1), NewId(1)),  # duplicates are NOT deduplicated
    (_NoOrigin(),),
    (1, _NoOrigin(), NewId(4)),
    (True, False),  # bool is an int subclass
    ("a", ""),  # str ids: "a" truthy, "" falsy with no origin
    (2**63, 2**70),  # beyond i64 — must not overflow the Rust path
]


@pytest.mark.parametrize("ids", CASES, ids=repr)
def test_rust_matches_python(ids):
    """The two implementations must agree element-for-element."""
    assert origin_ids_rust(ids) == _origin_ids_python(ids)


@pytest.mark.parametrize("ids", CASES, ids=repr)
def test_dispatch_is_type_agnostic(ids):
    """``_origin_ids`` must give the same answer for a tuple and a list.

    This is the property that actually matters at the call sites: the dispatch
    is an optimization, not a semantic choice.
    """
    assert _origin_ids(ids) == _origin_ids(list(ids))


def test_non_attribute_error_propagates_from_both():
    """A raising ``__getattr__`` is not swallowed by either implementation."""
    ids = (_RaisingOrigin(),)
    with pytest.raises(RuntimeError):
        origin_ids_rust(ids)
    with pytest.raises(RuntimeError):
        _origin_ids_python(ids)


def test_result_is_a_list_of_the_original_objects():
    """Kept ids are the original objects, not copies or coerced values."""
    a, b = 7, NewId(9)
    result = origin_ids_rust((a, b))
    assert result == [7, 9]
    assert result[0] is a
    assert result[1] is b.origin
