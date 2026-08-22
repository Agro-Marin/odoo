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


# Names two contracts may both hold, because two classes really do own a member
# of that name and collaborators really do reach both. Each entry is a decision,
# not a suppression: the pair is listed, so a *new* overlap still fails.
#
# `_discard` and `_load` are the two. `RelationalRecord._discard` rolls a record
# back to its save point; `StaticList._discard` restores a list's command log and
# membership. `RelationalRecord._load` re-reads one record; `StaticList._load`
# re-materialises a page. Same verb, different subject — which is also why
# `js_private_access.py` cannot attribute an access to either of them: its
# `is_declared` is an `any()` over every module declaring the name, precisely
# because a regex has no way to tell a record from a list.
ACKNOWLEDGED_OVERLAPS = {
    frozenset(
        {
            "model/relational_model/record_contract.js",
            "model/relational_model/static_list_contract.js",
        }
    ): {"_discard", "_load"},
}


def test_the_contracts_do_not_overlap_by_accident():
    surfaces = {
        filename: _array_members(_source(filename), array)
        for filename, array, _, _ in CONTRACTS
    }
    for i, (a_name, a_members) in enumerate(surfaces.items()):
        for b_name, b_members in list(surfaces.items())[i + 1 :]:
            allowed = ACKNOWLEDGED_OVERLAPS.get(frozenset({a_name, b_name}), set())
            shared = (a_members & b_members) - allowed
            assert not shared, (
                f"{a_name} and {b_name} both name: {sorted(shared)}. If two "
                "classes genuinely own a member of that name, add the pair to "
                "ACKNOWLEDGED_OVERLAPS with the reason."
            )


def test_every_acknowledged_overlap_is_still_a_real_one():
    """An exception list that outlives its exception is a lie. Each entry must
    still be shared by both contracts."""
    surfaces = {
        filename: _array_members(_source(filename), array)
        for filename, array, _, _ in CONTRACTS
    }
    for pair, members in ACKNOWLEDGED_OVERLAPS.items():
        a_name, b_name = sorted(pair)
        stale = members - (surfaces[a_name] & surfaces[b_name])
        assert not stale, (
            f"ACKNOWLEDGED_OVERLAPS still excuses {sorted(stale)} for "
            f"{a_name} / {b_name}, but they no longer overlap — drop the entry."
        )


# --------------------------------------------------------------------------
# The direction nothing checked: code -> contract.
#
# Every gate over these files runs contract -> code. `*_contract_conformance.test.js`
# asks whether the class still has what the contract names; the tests above ask
# whether the array and the typedef agree with each other. Nothing asked the
# question that actually bites: does the contract name everything a collaborator
# reaches?
#
# It did not. `RELATIONAL_MODEL_SURFACE` named `hooks`, which no collaborator
# used, while `lifecycleHooks` (8 uses) and `uiHooks` (9) were reached by four
# files each and named by nothing -- so renaming either would have kept every
# gate green and broken seventeen call sites.
#
# `js_private_access.py` covers the `_private` half and only that half, and even
# there it attributes an access to *any* module declaring a member of that name
# (`is_declared` is an `any()` over `owners`, because the scanner has no types).
# Public members it does not look at at all. This closes that.
# --------------------------------------------------------------------------

MODEL_DIR = "model/relational_model"

# Members of the `Model` base class, which `RelationalModel` inherits rather than
# owns. They belong to `model.js`'s surface, not to this contract.
_MODEL_BASE_MEMBERS = {
    "bus",
    "config",
    "env",
    "hasData",
    "isAlive",
    "isReady",
    "notify",
    "setup",
    "sampleData",
    "settleBeforeReload",
    "updateEpoch",
    "whenReady",
}

_MODEL_ACCESS = re.compile(r"\bmodel\.([A-Za-z_][A-Za-z0-9_]*)")


def _model_collaborators() -> list[Path]:
    directory = WEB_SRC / MODEL_DIR
    return sorted(
        p
        for p in directory.glob("*.js")
        if p.name != "relational_model.js" and not p.name.endswith("_contract.js")
    )


def test_every_model_member_a_collaborator_reaches_is_in_the_contract():
    surface = _array_members(
        _source("model/relational_model/relational_model_contract.js"),
        "RELATIONAL_MODEL_SURFACE",
    )
    collaborators = _model_collaborators()
    assert len(collaborators) > 15, "the scan found almost nothing — check MODEL_DIR"

    reached: dict[str, set[str]] = {}
    for path in collaborators:
        for member in _MODEL_ACCESS.findall(path.read_text(encoding="utf8")):
            if member in surface or member in _MODEL_BASE_MEMBERS:
                continue
            reached.setdefault(member, set()).add(path.name)

    assert not reached, (
        "reached on `model` by a collaborator but named by no contract: "
        + "; ".join(
            f"{member} <- {', '.join(sorted(files))}"
            for member, files in sorted(reached.items())
        )
        + ". Add it to RELATIONAL_MODEL_SURFACE and its typedef, or stop reaching for it."
    )


def test_the_scan_would_notice_a_member_leaving_the_contract():
    """A not-vacuous check: the assertion above passes trivially if the regex
    matches nothing, so drive it with a member removed from the surface."""
    surface = _array_members(
        _source("model/relational_model/relational_model_contract.js"),
        "RELATIONAL_MODEL_SURFACE",
    )
    surface.discard("mutex")
    reached = {
        member
        for path in _model_collaborators()
        for member in _MODEL_ACCESS.findall(path.read_text(encoding="utf8"))
        if member not in surface and member not in _MODEL_BASE_MEMBERS
    }
    assert "mutex" in reached, (
        "the scan did not see `model.mutex`, which every datapoint serialises on "
        "— the regex or the file list is wrong, and the check above is vacuous"
    )


# `RelationalRecord`'s half of the same question. A collaborator names its
# receiver `record`, so the scan is the same shape as the one above.
#
# There is deliberately no equivalent for `StaticList`: collaborators spell its
# receiver `list`, and so does `group.js` — where `this.list` is a *DynamicList*.
# A `list.<member>` scan therefore mixes two classes and reports the one's
# members as missing from the other's contract. Closing that needs the receiver's
# type, which a regex does not have.

# Members `DataPoint` provides, which `RelationalRecord` inherits rather than
# owns.
_DATAPOINT_MEMBERS = {
    "activeFields",
    "config",
    "context",
    "data",
    "evalContext",
    "evalContextWithVirtualIds",
    "fieldNames",
    "fields",
    "id",
    "model",
    "resModel",
}

_RECORD_ACCESS = re.compile(r"\brecord\.([A-Za-z_][A-Za-z0-9_]*)")


def _record_collaborators() -> list[Path]:
    directory = WEB_SRC / MODEL_DIR
    return sorted(
        p
        for p in directory.glob("*.js")
        if p.name != "record.js" and not p.name.endswith("_contract.js")
    )


def test_every_record_member_a_collaborator_reaches_is_in_a_contract():
    src = _source("model/relational_model/record_contract.js")
    surface = _array_members(src, "RECORD_CONTRACT_SURFACE") | _array_members(
        src, "RECORD_OWNER_SURFACE"
    )
    reached: dict[str, set[str]] = {}
    for path in _record_collaborators():
        for member in _RECORD_ACCESS.findall(path.read_text(encoding="utf8")):
            # `record.js` in prose and in import specifiers, not a member.
            if member == "js" or member in surface or member in _DATAPOINT_MEMBERS:
                continue
            reached.setdefault(member, set()).add(path.name)

    assert not reached, (
        "reached on `record` by a collaborator but named by no contract: "
        + "; ".join(
            f"{member} <- {', '.join(sorted(files))}"
            for member, files in sorted(reached.items())
        )
        + ". Add it to RECORD_CONTRACT_SURFACE (state a double must answer) or "
        "RECORD_OWNER_SURFACE (what an owner does to a record), and its typedef."
    )


def test_the_record_scan_would_notice_a_member_leaving_the_contract():
    src = _source("model/relational_model/record_contract.js")
    surface = _array_members(src, "RECORD_CONTRACT_SURFACE") | _array_members(
        src, "RECORD_OWNER_SURFACE"
    )
    surface.discard("resId")
    reached = {
        member
        for path in _record_collaborators()
        for member in _RECORD_ACCESS.findall(path.read_text(encoding="utf8"))
        if member not in surface and member not in _DATAPOINT_MEMBERS and member != "js"
    }
    assert "resId" in reached, (
        "the scan did not see `record.resId`, which eleven collaborator files "
        "read — the regex or the file list is wrong, and the check above is vacuous"
    )
