import pytest
from odoo_rust import origin_ids as origin_ids_rust

from odoo.orm.helpers import _origin_ids, _origin_ids_python
from odoo.orm.primitives import NewId


class _NoOrigin:
    def __bool__(self) -> bool:
        return False


class _RaisingOrigin:
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
    (NewId(0),),
    (NewId(-3),),
    (1, NewId(2), 0, NewId(), 3),
    (NewId(1), NewId(1)),
    (_NoOrigin(),),
    (1, _NoOrigin(), NewId(4)),
    (True, False),
    ("a", ""),
    (2**63, 2**70),
]


@pytest.mark.parametrize("ids", CASES, ids=repr)
def test_rust_matches_python(ids):
    assert origin_ids_rust(ids) == _origin_ids_python(ids)


@pytest.mark.parametrize("ids", CASES, ids=repr)
def test_dispatch_is_type_agnostic(ids):
    assert _origin_ids(ids) == _origin_ids(list(ids))


def test_non_attribute_error_propagates_from_both():
    ids = (_RaisingOrigin(),)
    with pytest.raises(RuntimeError):
        origin_ids_rust(ids)
    with pytest.raises(RuntimeError):
        _origin_ids_python(ids)


def test_result_is_a_list_of_the_original_objects():
    a, b = 7, NewId(9)
    result = origin_ids_rust((a, b))
    assert result == [7, 9]
    assert result[0] is a
    assert result[1] is b.origin
