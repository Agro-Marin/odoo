import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="test_record_contract_agreement")
WEB_SRC = ROOT / "addons/web/static/src"

CONTRACTS = [
    (
        "model/relational_model/record_contract.js",
        "RECORD_CONTRACT_SURFACE",
        "RecordContract",
        20,
    ),
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
    body = re.search(rf"@typedef \{{\{{((?:(?!\}}\}} )[\s\S])*?)\}}\}} {name}", src)
    assert body, f"{name} typedef not found"
    return set(re.findall(r"^\s*\*\s+([A-Za-z_$][\w$]*):", body.group(1), re.MULTILINE))


@pytest.mark.parametrize(("filename", "array", "typedef", "floor"), CONTRACTS)
def test_both_declarations_are_found(filename, array, typedef, floor):
    src = _source(filename)
    assert len(_array_members(src, array)) >= floor
    assert len(_typedef_members(src, typedef)) >= floor


@pytest.mark.parametrize(("filename", "array", "typedef", "floor"), CONTRACTS)
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
    surfaces = {
        filename: _array_members(_source(filename), array)
        for filename, array, _, _ in CONTRACTS
    }
    for i, (a_name, a_members) in enumerate(surfaces.items()):
        for b_name, b_members in list(surfaces.items())[i + 1 :]:
            shared = a_members & b_members
            assert not shared, f"{a_name} and {b_name} both name: {sorted(shared)}"
