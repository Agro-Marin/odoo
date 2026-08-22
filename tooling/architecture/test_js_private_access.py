import pathlib

import doc_measured
import js_private_access as jpa


def _tree(root, files):
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
    assert not _members(
        tmp_path,
        {
            "a/owner.js": "class A {\n    constructor() {\n        this._context = 1;\n    }\n}\n",
            "a/user.js": "class B {\n    setup() {\n        return this.props._context;\n    }\n}\n",
        },
    )


def test_a_member_declared_in_several_modules_still_counts_for_an_outsider(tmp_path):
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


def test_real_web_tree_is_scanned():
    found, _undeclared, public = jpa.measure()
    assert len(jpa.iter_source_files()) > 500, "expected the real web src to be found"
    assert found, "expected the pinned debt to still be measurable"
    assert public > 0
    writes = [a for a in found if a.write]
    # Bounded, not non-empty. The docstring's whole argument is that the write
    # half should be driven to zero first, so asserting a write still exists
    # here would forbid the outcome the gate exists to reach -- and it did, on
    # the commit that reached it. That the scanner can SEE a write is pinned
    # against synthetic fixtures instead (test_cross_module_write_is_counted_as_a_write
    # and its two neighbours), which is where a detection test belongs: it does
    # not depend on the tree still being broken.
    assert len(writes) <= len(found) / 4, "writes must never dominate the budget"


def test_the_debt_is_concentrated_where_the_docstring_says_it_is():
    found, _, _ = jpa.measure()
    clustered = sum(
        1
        for a in found
        if a.module.startswith(("model/relational_model/", "webclient/actions/"))
    )
    assert clustered > 0.85 * len(found)


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
    assert not _contract_tree(
        tmp_path,
        {"m/ghost_contract.js": 'export const GHOST_SURFACE = ["_op"];\n'},
    )


def test_only_SURFACE_arrays_are_the_contract(tmp_path):

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


def test_module_docstring_measured_block_is_fresh():

    found, undeclared, public = jpa.measure()
    metrics = jpa.doc_metrics(
        found,
        undeclared,
        public,
        jpa.declared_contracts(),
        jpa.internal_collaborators(),
    )
    problems = doc_measured.check(pathlib.Path(jpa.__file__), metrics)
    assert not problems, (
        "stale MEASURED block:\n  "
        + "\n  ".join(problems)
        + ("\n\n  python tooling/architecture/js_private_access.py --update-doc")
    )


# --- the cross-tree scope -------------------------------------------------
#
# `measure` cannot see these by construction: it resolves a member's owner from
# the tree it is pointed at, so aimed at a consuming addon it finds no owner and
# reports nothing. These tests drive `measure_cross_tree`, which indexes both.


def _addon_tree(root, addons):
    """Build `<root>/addons/<name>/static/src/...` for each addon given."""
    for addon, files in addons.items():
        src = root / "addons" / addon / "static" / "src"
        for rel, body in files.items():
            path = src / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        src.mkdir(parents=True, exist_ok=True)
    return root


def _cross(root):
    web_src = root / "addons" / "web" / "static" / "src"
    return {
        (a.addon, a.module, a.base, a.member, a.write)
        for a in jpa.measure_cross_tree(root=root, web_src=web_src)
    }


def test_an_addon_reading_a_web_private_is_counted(tmp_path):
    _addon_tree(
        tmp_path,
        {
            "web": {"model/record.js": "class R {\n    _values = {};\n}\n"},
            "account": {"form.js": "const x = record._values.rounding;\n"},
        },
    )
    assert _cross(tmp_path) == {
        ("account", "account/static/src/form.js", "record", "_values", False)
    }


def test_a_write_is_flagged_as_a_write(tmp_path):
    _addon_tree(
        tmp_path,
        {
            "web": {"model/record.js": "class R {\n    _update() {}\n}\n"},
            "documents": {"mixin.js": "record._update = async () => {};\n"},
        },
    )
    assert _cross(tmp_path) == {
        ("documents", "documents/static/src/mixin.js", "record", "_update", True)
    }


def test_a_member_the_addon_declares_is_its_own(tmp_path):
    # No type inference is attempted, so declaring the name anywhere in the
    # addon is taken as ownership. That is the whole precision budget.
    _addon_tree(
        tmp_path,
        {
            "web": {"model/record.js": "class R {\n    _values = {};\n}\n"},
            "sale": {
                "own.js": "class Mine {\n    _values = {};\n}\n",
                "use.js": "const x = thing._values;\n",
            },
        },
    )
    assert _cross(tmp_path) == set()


def test_web_looking_at_itself_is_the_other_scope(tmp_path):
    _addon_tree(
        tmp_path,
        {
            "web": {
                "model/record.js": "class R {\n    _values = {};\n}\n",
                "views/list.js": "const x = record._values;\n",
            }
        },
    )
    assert _cross(tmp_path) == set()


def test_a_pinned_plain_object_member_is_not_counted(tmp_path):
    _addon_tree(
        tmp_path,
        {
            "web": {"model/record.js": "class R {\n    _id = 1;\n}\n"},
            "html_builder": {"list.js": "const x = item._id;\n"},
        },
    )
    assert ("html_builder", "_id") in jpa.PLAIN_OBJECT_MEMBERS
    assert _cross(tmp_path) == set()


def test_every_pin_carries_a_reason():
    for key, reason in jpa.PLAIN_OBJECT_MEMBERS.items():
        assert isinstance(reason, str) and len(reason) > 40, key


def test_a_pin_that_matches_nothing_is_stale():
    # A pin whose access disappeared is an exemption nobody is using, and it
    # would silently excuse the name if it came back somewhere else.
    found = jpa.measure_cross_tree()
    live = {(a.addon, a.member) for a in found}
    web_declared = jpa.addon_private_names(jpa.WEB_SRC)
    for addon, member in jpa.PLAIN_OBJECT_MEMBERS:
        assert member in web_declared, f"{addon}.{member}: web no longer declares it"
        assert (addon, member) not in live, f"{addon}.{member}: pin has no effect"
