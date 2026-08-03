"""The record contract is declared twice; the two declarations must agree.

``record_contract.js`` states the surface as a runtime array
(``RECORD_CONTRACT_SURFACE``, which the conformance suite checks a real
``RelationalRecord`` and the test double against) and as a JSDoc typedef
(``RecordContract``, which is what satellites annotate so that reaching past the
contract is a typecheck failure rather than an invisible +1 in the
private-access budget).

Neither can check the other. The array is a runtime value a JS test can iterate;
the typedef is erased before anything runs, and no JS test can see it. So the two
drift silently — and the failure mode is the worse direction: a member added to
the array but not the typedef leaves satellites unable to use it, while one added
to the typedef but not the array is a contract member nothing conformance-tests.

Stdlib + pytest only, like the gates beside it. It is a ``test_`` file, so
``test_every_gate_refuses_an_empty_tree`` does not require it to be registered —
it is a test, not a gate, and it asserts an equality rather than scanning a tree.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
WEB_SRC = ROOT / "addons/web/static/src"

# (file, exported array, typedef name, floor). The floor is a guard, not a
# target: a regex that silently matched nothing would make every assertion here
# vacuously true, which is the failure mode this whole directory exists to
# refuse.
CONTRACTS = [
    ("model/relational_model/record_contract.js", "RECORD_CONTRACT_SURFACE", "RecordContract", 20),
    (
        "model/relational_model/record_contract.js",
        "RECORD_OWNER_SURFACE",
        "RecordOwnerContract",
        10,
    ),
    (
        "model/relational_model/static_list_contract.js",
        "STATIC_LIST_OWNER_SURFACE",
        "StaticListContract",
        10,
    ),
    (
        "model/relational_model/dynamic_list_contract.js",
        "DYNAMIC_LIST_OWNER_SURFACE",
        "DynamicListContract",
        # Deliberately the smallest floor here. `DynamicList` is reached five
        # times for four members and every one is an operation, so unlike
        # `StaticList` there is no working-memory residue to separate out. A
        # floor of 10 would fail an accurate contract for being short.
        3,
    ),
    (
        "model/relational_model/relational_model_contract.js",
        "RELATIONAL_MODEL_SURFACE",
        "RelationalModelContract",
        15,
    ),
    (
        "webclient/actions/action_service_contract.js",
        "ACTION_MANAGER_SURFACE",
        "ActionManagerContract",
        15,
    ),
]


def _source(filename: str) -> str:
    path = WEB_SRC / filename
    assert path.is_file(), f"no contract at {path}"
    return path.read_text(encoding="utf8")


def _array_members(src: str, name: str) -> set[str]:
    body = re.search(rf"{name} = \[(.*?)\n\];", src, re.DOTALL)
    assert body, f"{name} array not found"
    return set(re.findall(r'"([^"]+)"', body.group(1)))


def _typedef_members(src: str, name: str) -> set[str]:
    # `(?:(?!\}\} )[\s\S])*?` rather than `.*?`: a file may hold several
    # typedefs, and a plain non-greedy match starts at the FIRST `@typedef {{`
    # and runs to the named closer, swallowing every typedef in between. That is
    # not hypothetical — `record_contract.js` grew a second typedef and this
    # test failed on itself, reporting the owner surface's members as the
    # satellite surface's. The inner guard stops the match at the first closer.
    body = re.search(
        rf"@typedef \{{\{{((?:(?!\}}\}} )[\s\S])*?)\}}\}} {name}", src
    )
    assert body, f"{name} typedef not found"
    # Property names at the start of a line, before their `:` type.
    return set(re.findall(r"^\s*\*\s+([A-Za-z_$][\w$]*):", body.group(1), re.MULTILINE))


@pytest.mark.parametrize("filename,array,typedef,floor", CONTRACTS)
def test_both_declarations_are_found(filename, array, typedef, floor):
    """Guard the regexes: an empty match would make every assertion vacuous."""
    src = _source(filename)
    assert len(_array_members(src, array)) >= floor
    assert len(_typedef_members(src, typedef)) >= floor


@pytest.mark.parametrize("filename,array,typedef,floor", CONTRACTS)
def test_the_array_and_the_typedef_name_the_same_members(
    filename, array, typedef, floor
):
    src = _source(filename)
    a, t = _array_members(src, array), _typedef_members(src, typedef)
    assert a == t, (
        f"{filename}: in the typedef but not the array: {sorted(t - a)}; "
        f"in the array but not the typedef: {sorted(a - t)}"
    )


def test_the_contracts_do_not_overlap_by_accident():
    """Members with the same NAME on different classes mean different things —
    `_load` on a record, a list and a model are three unrelated operations. A
    member drifting from one contract into another would be silent, and would
    then typecheck call sites against the wrong shape."""
    surfaces = {
        filename: _array_members(_source(filename), array)
        for filename, array, _, _ in CONTRACTS
    }
    for i, (a_name, a_members) in enumerate(surfaces.items()):
        for b_name, b_members in list(surfaces.items())[i + 1 :]:
            shared = a_members & b_members
            assert not shared, f"{a_name} and {b_name} both name: {sorted(shared)}"
