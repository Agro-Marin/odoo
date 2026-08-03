"""Tests for the cross-module private-access budget.

Stdlib + pytest only — no Odoo imports — so this runs in the same
database-free way as the checker itself. Run with:

    pytest tooling/architecture/test_js_private_access.py

Every behavioural test builds a synthetic ``static/src`` tree, so the suite does
not change meaning as the real debt is paid down. The tests that read the real
tree assert only what a measurement gate can silently lose: that it found its
inputs, and that the two halves it separates stay separated.
"""

import js_private_access as jpa  # sys.path set by conftest.py


def _tree(root, files):
    """``files`` maps a path under ``src/`` to its source text."""
    src = root / "src"
    for rel, body in files.items():
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    src.mkdir(parents=True, exist_ok=True)
    return src


def _members(root, files):
    found, _, _ = jpa.measure(_tree(root, files))
    return {(a.module, a.base, a.member, a.write) for a in found}


# --- what is and is not an access ---


def test_own_private_is_not_an_access(tmp_path):
    assert not _members(
        tmp_path,
        {
            "a/owner.js": "class A {\n    _x() {}\n    go() {\n        other._x();\n    }\n}\n"
        },
    )


def test_this_is_never_an_access(tmp_path):
    assert not _members(
        tmp_path,
        {
            "a/owner.js": "class A {\n    _x() {}\n}\n",
            "a/user.js": "class B {\n    go() {\n        this._x();\n    }\n}\n",
        },
    )


def test_super_is_never_an_access(tmp_path):
    assert not _members(
        tmp_path,
        {
            "a/owner.js": "class A {\n    _x() {}\n}\n",
            "a/user.js": "class B {\n    go() {\n        super._x();\n    }\n}\n",
        },
    )


def test_cross_module_read_is_counted_as_a_read(tmp_path):
    assert _members(
        tmp_path,
        {
            "a/owner.js": "class A {\n    _x() {}\n}\n",
            "a/user.js": "export function go(rec) {\n    return rec._x();\n}\n",
        },
    ) == {("a/user.js", "rec", "_x", False)}


def test_cross_module_write_is_counted_as_a_write(tmp_path):
    assert _members(
        tmp_path,
        {
            "a/owner.js": "class A {\n    constructor() {\n        this._x = 1;\n    }\n}\n",
            "a/user.js": "export function go(rec) {\n    rec._x = 2;\n}\n",
        },
    ) == {("a/user.js", "rec", "_x", True)}


def test_comparison_is_a_read_not_a_write(tmp_path):
    # `===` after the member must not read as assignment; that would inflate the
    # half of the budget meant to be small enough to clear.
    found = _members(
        tmp_path,
        {
            "a/owner.js": "class A {\n    constructor() {\n        this._x = 1;\n    }\n}\n",
            "a/user.js": "export function go(rec) {\n    return rec._x === 2;\n}\n",
        },
    )
    assert found == {("a/user.js", "rec", "_x", False)}


def test_compound_assignment_is_a_write(tmp_path):
    found = _members(
        tmp_path,
        {
            "a/owner.js": "class A {\n    constructor() {\n        this._n = 0;\n    }\n}\n",
            "a/user.js": "export function go(rec) {\n    rec._n += 1;\n}\n",
        },
    )
    assert found == {("a/user.js", "rec", "_n", True)}


def test_accesses_inside_comments_and_strings_do_not_count(tmp_path):
    assert not _members(
        tmp_path,
        {
            "a/owner.js": "class A {\n    _x() {}\n}\n",
            "a/user.js": (
                "// rec._x()\n"
                "/** @param {A} rec — rec._x() is internal */\n"
                'export const s = "rec._x()";\n'
                "export const t = `rec._x()`;\n"
            ),
        },
    )


def test_a_props_bag_key_is_not_a_class_member(tmp_path):
    # `props._x` is a contract between a component and its instantiator. Name
    # matching blamed `controller_component.js`'s `props._context` on
    # `SearchModel._context`, which declares the same name and nothing else.
    assert not _members(
        tmp_path,
        {
            "a/owner.js": "class A {\n    constructor() {\n        this._context = 1;\n    }\n}\n",
            "a/user.js": "class B {\n    setup() {\n        return this.props._context;\n    }\n}\n",
        },
    )


# --- attribution ---


def test_a_member_declared_in_several_modules_still_counts_for_an_outsider(tmp_path):
    # `_load` is declared in five DataPoint subclasses. Which one a call reaches
    # has no single answer; that the caller is none of them always does.
    found, _, _ = jpa.measure(
        _tree(
            tmp_path,
            {
                "m/one.js": "class One {\n    _load() {}\n}\n",
                "m/two.js": "class Two {\n    _load() {}\n}\n",
                "m/user.js": "export function go(dp) {\n    dp._load();\n}\n",
            },
        )
    )
    assert [(a.module, a.member) for a in found] == [("m/user.js", "_load")]
    assert found[0].owners == ("m/one.js", "m/two.js")


def test_a_declarer_accessing_the_shared_name_is_not_a_violation(tmp_path):
    assert not _members(
        tmp_path,
        {
            "m/one.js": "class One {\n    _load() {\n        other._load();\n    }\n}\n",
            "m/two.js": "class Two {\n    _load() {}\n}\n",
        },
    )


def test_undeclared_members_are_reported_apart_and_not_counted(tmp_path):
    found, undeclared, _ = jpa.measure(
        _tree(
            tmp_path, {"a/user.js": "export function go(a) {\n    a._stamped = 1;\n}\n"}
        )
    )
    assert found == []
    assert undeclared == {"_stamped": 1}


# --- the companion metric that makes gaming visible ---


def test_promoting_a_private_moves_the_count_into_public_members(tmp_path):
    private = {
        "model/relational_model/owner.js": "class A {\n    _x() {}\n}\n",
        "model/relational_model/user.js": "export function go(r) {\n    r._x();\n}\n",
    }
    found, _, public_before = jpa.measure(_tree(tmp_path / "before", private))
    assert len(found) == 1

    promoted = {
        "model/relational_model/owner.js": "class A {\n    x() {}\n}\n",
        "model/relational_model/user.js": "export function go(r) {\n    r.x();\n}\n",
    }
    found_after, _, public_after = jpa.measure(_tree(tmp_path / "after", promoted))
    assert found_after == [], "the budget is satisfiable by renaming"
    assert public_after > public_before, (
        "renaming must show up in the companion count, or the budget can be "
        "gamed with nothing to see in review"
    )


# --- the second verdict: cross-layer access is drift-zero ---


def _access(module, owners, member="_x"):
    return jpa.Access(
        module=module, line=1, base="obj", member=member, write=False, owners=owners
    )


def test_reaching_into_another_layer_is_cross_layer():
    assert jpa.is_cross_layer(
        _access("views/kanban/kanban_controller.js", ("model/relational_model/x.js",))
    )


def test_reaching_into_your_own_layer_is_not():
    assert not jpa.is_cross_layer(
        _access("model/relational_model/a.js", ("model/relational_model/b.js",))
    )


def test_one_owner_in_the_accessors_layer_is_enough():
    # The heaviest names are ambiguous, and `list._cache` resolves to both
    # `orm_service` and `static_list`. Blaming that on core/ would invent a
    # layering violation out of a name collision.
    assert not jpa.is_cross_layer(
        _access(
            "model/relational_model/static_list_sort.js",
            ("core/network/orm_service.js", "model/relational_model/static_list.js"),
        )
    )


def test_check_fails_on_a_cross_layer_access_whatever_the_total(monkeypatch):
    monkeypatch.setattr(
        jpa,
        "measure",
        lambda: (
            [_access("views/kanban/k.js", ("model/relational_model/x.js",))],
            jpa.Counter(),
            0,
        ),
    )
    assert jpa.main([]) == 0, "report mode must not fail"
    assert jpa.main(["--check"]) == 1


def test_check_passes_when_only_friend_coupling_remains(monkeypatch):
    monkeypatch.setattr(
        jpa,
        "measure",
        lambda: (
            [_access("model/relational_model/a.js", ("model/relational_model/b.js",))]
            * 50,
            jpa.Counter(),
            0,
        ),
    )
    assert jpa.main(["--check"]) == 0, (
        "the total is shrink-only and ratcheted elsewhere; only cross-layer fails here"
    )


# --- the gate must actually reach the real tree ---


def test_real_web_tree_is_scanned():
    found, _undeclared, public = jpa.measure()
    assert len(jpa.iter_source_files()) > 500, "expected the real web src to be found"
    assert found, "expected the pinned debt to still be measurable"
    assert public > 0
    # Writes are the half meant to be cleared first, so they must stay a small,
    # separately visible fraction rather than being folded into the total.
    writes = [a for a in found if a.write]
    assert 0 < len(writes) < len(found) / 4


def test_the_debt_is_concentrated_where_the_docstring_says_it_is():
    # If this ever fails, the budget grew somewhere new and the docstring's
    # account of what it measures is stale.
    found, _, _ = jpa.measure()
    clustered = sum(
        1
        for a in found
        if a.module.startswith(("model/relational_model/", "webclient/actions/"))
    )
    assert clustered > 0.85 * len(found)


# --- declared contracts ---
#
# A module may publish the members other modules are meant to reach, in a
# sibling `<x>_contract.js`. Those accesses are no longer debt, and counting
# them with the rest means the budget cannot show the debt falling.


def _contract_tree(root, files):
    return jpa.declared_contracts(_tree(root, files))


def test_a_sibling_contract_declares_its_owners_members(tmp_path):
    contracts = _contract_tree(
        tmp_path,
        {
            "m/thing.js": "class Thing {\n    _op() {}\n}\n",
            "m/thing_contract.js": 'export const THING_SURFACE = [\n    "_op",\n];\n',
        },
    )
    assert contracts == {"m/thing.js": {"_op"}}


def test_a_contract_with_no_owner_beside_it_is_ignored(tmp_path):
    # The name is a convention, not a declaration: without `<x>.js` there is
    # nothing for the members to be the interface OF.
    assert not _contract_tree(
        tmp_path,
        {"m/ghost_contract.js": 'export const GHOST_SURFACE = ["_op"];\n'},
    )


def test_only_SURFACE_arrays_are_the_contract(tmp_path):
    """The trap this classification exists to avoid.

    `static_list_contract.js` exports the interface AND, deliberately apart, the
    working memory that helpers still reach for. Treating every array in the
    file as declared would count that residue as honoured — marking the debt
    paid by writing it down.
    """
    contracts = _contract_tree(
        tmp_path,
        {
            "m/thing.js": "class Thing {\n    _op() {}\n    _guts() {}\n}\n",
            "m/thing_contract.js": (
                'export const THING_SURFACE = [\n    "_op",\n];\n'
                'export const INTERNAL_STATE_REACHED = [\n    "_guts",\n];\n'
            ),
        },
    )
    assert contracts == {"m/thing.js": {"_op"}}


def test_an_access_to_a_declared_member_is_not_undeclared(tmp_path):
    src = _tree(
        tmp_path,
        {
            "m/thing.js": "class Thing {\n    _op() {}\n    _guts() {}\n}\n",
            "m/thing_contract.js": (
                'export const THING_SURFACE = [\n    "_op",\n];\n'
                'export const INTERNAL_STATE_REACHED = [\n    "_guts",\n];\n'
            ),
            "m/user.js": "export function f(thing) {\n    thing._op();\n    thing._guts();\n}\n",
        },
    )
    found, _, _ = jpa.measure(src)
    contracts = jpa.declared_contracts(src)
    declared = {a.member for a in found if jpa.is_declared(a, contracts)}
    undeclared = {a.member for a in found if not jpa.is_declared(a, contracts)}
    assert declared == {"_op"}
    assert undeclared == {"_guts"}, "working memory must still count as debt"


# --- module-internal collaborators ---
#
# A class split for size keeps a boundary its files do not describe. Access from
# inside that boundary is not cross-module coupling, and counting it as such
# drowns the accesses that are.


def test_a_declared_collaborator_is_module_internal(tmp_path):
    src = _tree(
        tmp_path,
        {
            "m/thing.js": "class Thing {\n    _guts() {}\n}\n",
            "m/thing_contract.js": (
                'export const THING_SURFACE = [\n    "_op",\n];\n'
                "export const INTERNAL_COLLABORATORS = [\n"
                '    "m/thing_helper.js",\n];\n'
            ),
            "m/thing_helper.js": "export function f(thing) {\n    thing._guts();\n}\n",
            "m/outsider.js": "export function g(thing) {\n    thing._guts();\n}\n",
        },
    )
    found, _, _ = jpa.measure(src)
    groups = jpa.internal_collaborators(src)
    internal = {a.module for a in found if jpa.is_internal(a, groups)}
    external = {a.module for a in found if not jpa.is_internal(a, groups)}
    assert internal == {"m/thing_helper.js"}
    assert external == {"m/outsider.js"}, "an outsider must still be counted"


def test_collaborators_and_the_contract_are_read_separately(tmp_path):
    """`INTERNAL_COLLABORATORS` holds module paths, `*_SURFACE` holds member
    names. Reading either list into the other would make every collaborator
    path look like a declared member, and silently."""
    files = {
        "m/thing.js": "class Thing {\n    _op() {}\n}\n",
        "m/thing_contract.js": (
            'export const THING_SURFACE = [\n    "_op",\n];\n'
            'export const INTERNAL_COLLABORATORS = [\n    "m/helper.js",\n];\n'
        ),
    }
    src = _tree(tmp_path, files)
    assert jpa.declared_contracts(src) == {"m/thing.js": {"_op"}}
    assert jpa.internal_collaborators(src) == {"m/thing.js": {"m/helper.js"}}


def test_a_contract_without_collaborators_declares_none(tmp_path):
    assert not jpa.internal_collaborators(
        _tree(
            tmp_path,
            {
                "m/thing.js": "class Thing {\n    _op() {}\n}\n",
                "m/thing_contract.js": 'export const THING_SURFACE = ["_op"];\n',
            },
        )
    )
