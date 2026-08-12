"""Tests for the JS extension-surface ratchet.

Stdlib + pytest only — no Odoo imports — so this runs in the same
database-free way as the checker itself. Run with:

    pytest tooling/architecture/test_js_extension_surface.py

The measurement tests build synthetic trees — a small ``web`` addon plus
consumer addons — so they keep their meaning as the real surface shrinks. Each
one pins a resolution form the gate must understand, and every form here was
found missing from an earlier draft rather than imagined: the first scanner
walked only *direct* subclasses and undercut the real surface by roughly a
quarter, which is what ``test_a_grandchild_is_attributed_to_the_web_ancestor``
and its neighbours exist to stop coming back.

The three tests that read the real tree assert what a measurement gate silently
loses: that it found its inputs, that the pin it judges against is the tree's
own, and that its docstring's MEASURED block still describes the tree.
"""

from pathlib import Path

import js_extension_surface as jes  # sys.path set by conftest.py
import pytest


def _write(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf8")
    return path


@pytest.fixture
def tree(tmp_path):
    """A synthetic workspace: ``addons/web`` plus room for consumer addons.

    Returns ``(root, web_src)``; hand both to the gate so nothing resolves
    against the real checkout.
    """
    web_src = tmp_path / "addons" / "web" / "static" / "src"
    web_src.mkdir(parents=True)
    return tmp_path, web_src


def measure(tree, **kwargs):
    root, web_src = tree
    return jes.measure_detailed((root,), web_src=web_src, **kwargs)


def points(tree):
    return set(measure(tree))


# --- what counts as an override point ---


def test_a_plain_subclass_overriding_a_base_method_is_a_point(tree):
    root, web_src = tree
    _write(
        web_src, "views/form.js", "export class FormController {\n    save() {}\n}\n"
    )
    _write(
        root,
        "addons/sale/static/src/x.js",
        'import { FormController } from "@web/views/form";\n'
        "export class SaleForm extends FormController {\n    save() {}\n}\n",
    )
    assert points(tree) == {"FormController.save"}


def test_a_method_the_base_does_not_declare_is_not_a_point(tree):
    root, web_src = tree
    _write(
        web_src, "views/form.js", "export class FormController {\n    save() {}\n}\n"
    )
    _write(
        root,
        "addons/sale/static/src/x.js",
        'import { FormController } from "@web/views/form";\n'
        "export class SaleForm extends FormController {\n    somethingNew() {}\n}\n",
    )
    assert points(tree) == set()


def test_owl_boilerplate_members_are_not_contract(tree):
    # Overriding `template` or `props` says nothing about the base's behaviour.
    root, web_src = tree
    _write(
        web_src,
        "views/form.js",
        "export class FormController {\n"
        "    static template = 'a';\n"
        "    static props = {};\n"
        "    save() {}\n"
        "}\n",
    )
    _write(
        root,
        "addons/sale/static/src/x.js",
        'import { FormController } from "@web/views/form";\n'
        "export class SaleForm extends FormController {\n"
        "    static template = 'b';\n"
        "    static props = {};\n"
        "}\n",
    )
    assert points(tree) == set()


def test_a_subclass_inside_web_is_not_surface(tree):
    # web extending its own class is internal by definition.
    _root, web_src = tree
    _write(
        web_src, "views/form.js", "export class FormController {\n    save() {}\n}\n"
    )
    _write(
        web_src,
        "views/settings.js",
        'import { FormController } from "@web/views/form";\n'
        "export class SettingsController extends FormController {\n    save() {}\n}\n",
    )
    assert points(tree) == set()


def test_a_subclass_in_webs_own_tests_is_not_surface(tree):
    """web's suite is not a downstream consumer.

    ``static/tests/`` is outside ``static/src``, so a predicate scoped to the
    source directory counts web's own tests as external and writes them into the
    pin — which then drifts whenever anyone edits a web test, i.e. on changes
    that cross no boundary at all. Three real points and seven sites entered the
    first pin this way.
    """
    root, web_src = tree
    _write(
        web_src, "views/form.js", "export class FormController {\n    save() {}\n}\n"
    )
    _write(
        root,
        "addons/web/static/tests/form.test.js",
        'import { FormController } from "@web/views/form";\n'
        "class Probe extends FormController {\n    save() {}\n}\n",
    )
    assert points(tree) == set()


# --- resolution forms: each was missing from an earlier draft ---


def test_a_grandchild_is_attributed_to_the_web_ancestor(tree):
    """The regression this gate exists to keep fixed.

    ``A extends B extends FormController`` is an override of web's contract.
    A direct-subclass-only walk sees `B` as A's base, finds it outside web, and
    drops the point — which is how the first measurement came in ~26% low.
    """
    root, web_src = tree
    _write(
        web_src, "views/form.js", "export class FormController {\n    save() {}\n}\n"
    )
    _write(
        root,
        "addons/project/static/src/mid.js",
        'import { FormController } from "@web/views/form";\n'
        "export class ProjectForm extends FormController {}\n",
    )
    _write(
        root,
        "addons/fsm/static/src/leaf.js",
        'import { ProjectForm } from "@project/mid";\n'
        "export class FsmForm extends ProjectForm {\n    save() {}\n}\n",
    )
    assert points(tree) == {"FormController.save"}


def test_an_alias_absent_from_tsconfig_still_resolves(tree):
    """Aliases come from the addon layout, not ``tsconfig.json``.

    ``tsconfig.json``'s ``paths`` map covers a minority of the aliases in use
    fork-wide. A resolver trusting it loses every chain through the rest — the
    real ``FsmProjectTaskFormController`` reaches ``FormController`` via
    ``@project``, which is one of them.
    """
    root, web_src = tree
    _write(
        web_src, "views/form.js", "export class FormController {\n    save() {}\n}\n"
    )
    _write(
        root,
        "addons/nowhere_in_tsconfig/static/src/x.js",
        'import { FormController } from "@web/views/form";\n'
        "export class Odd extends FormController {\n    save() {}\n}\n",
    )
    assert points(tree) == {"FormController.save"}


def test_a_descriptor_property_base_resolves(tree):
    # `class X extends formView.Controller` — 37 real sites.
    root, web_src = tree
    _write(
        web_src,
        "views/form.js",
        "export class FormController {\n    save() {}\n}\n"
        "export const formView = {\n    Controller: FormController,\n};\n",
    )
    _write(
        root,
        "addons/website/static/src/x.js",
        'import { formView } from "@web/views/form";\n'
        "export class PageForm extends formView.Controller {\n    save() {}\n}\n",
    )
    assert points(tree) == {"FormController.save"}


def test_a_mixin_wrapped_base_resolves(tree):
    # `class X extends AiFieldMixin(CharField)` — 67 real sites.
    root, web_src = tree
    _write(
        web_src, "fields/char.js", "export class CharField {\n    onChange() {}\n}\n"
    )
    _write(
        root,
        "addons/ai/static/src/x.js",
        'import { CharField } from "@web/fields/char";\n'
        "const Mixin = (c) => class extends c {};\n"
        "export class AiChar extends Mixin(CharField) {\n    onChange() {}\n}\n",
    )
    assert points(tree) == {"CharField.onChange"}


def test_an_aliased_import_resolves_to_the_original_export(tree):
    """`import { A as B }` binds B locally; the target module exports A.

    Looking B up in the target resolves nothing, and the failure is silent —
    the consumer simply vanishes from the surface. Four real points hid behind
    this (`FileViewer.setup`/`close`/`next`/`previous`, patched by
    enterprise/sign as `WebFileViewer`).
    """
    root, web_src = tree
    _write(
        web_src,
        "components/file_viewer.js",
        "export class FileViewer {\n    setup() {}\n}\n",
    )
    _write(
        root,
        "addons/sign/static/src/v.js",
        'import { FileViewer as WebFileViewer } from "@web/components/file_viewer";\n'
        "patch(WebFileViewer.prototype, {\n    setup() {},\n});\n",
    )
    assert points(tree) == {"FileViewer.setup"}


def test_an_aliased_import_resolves_for_extends_too(tree):
    root, web_src = tree
    _write(web_src, "a.js", "export class Thing {\n    go() {}\n}\n")
    _write(
        root,
        "addons/x/static/src/s.js",
        'import { Thing as Renamed } from "@web/a";\n'
        "export class Sub extends Renamed {\n    go() {}\n}\n",
    )
    assert points(tree) == {"Thing.go"}


def test_a_face_reexport_resolves_to_the_defining_module(tree):
    root, web_src = tree
    _write(
        web_src,
        "views/form/form_controller.js",
        "export class FormController {\n    save() {}\n}\n",
    )
    _write(
        web_src,
        "views/form.js",
        'export { FormController } from "./form/form_controller";\n',
    )
    _write(
        root,
        "addons/sale/static/src/x.js",
        'import { FormController } from "@web/views/form";\n'
        "export class SaleForm extends FormController {\n    save() {}\n}\n",
    )
    assert points(tree) == {"FormController.save"}


def test_the_point_is_owned_by_the_nearest_ancestor_declaring_it(tree):
    """Attribution follows the contract actually being overridden.

    ``ListController`` and ``FormController`` both declare
    ``beforeExecuteActionButton`` in the real tree, and a list subclass overrides
    the former's. Attributing to the outermost ancestor would file it under the
    wrong owner and make the pin unactionable.
    """
    root, web_src = tree
    _write(web_src, "views/base.js", "export class Base {\n    run() {}\n}\n")
    _write(
        web_src,
        "views/list.js",
        'import { Base } from "@web/views/base";\n'
        "export class ListController extends Base {\n    run() {}\n}\n",
    )
    _write(
        root,
        "addons/portal/static/src/x.js",
        'import { ListController } from "@web/views/list";\n'
        "export class PortalList extends ListController {\n    run() {}\n}\n",
    )
    assert points(tree) == {"ListController.run"}


def test_a_class_named_like_a_web_class_but_locally_defined_is_not_surface(tree):
    root, web_src = tree
    _write(
        web_src, "views/form.js", "export class FormController {\n    save() {}\n}\n"
    )
    _write(
        root,
        "addons/sale/static/src/x.js",
        "class FormController {\n    save() {}\n}\n"
        "export class SaleForm extends FormController {\n    save() {}\n}\n",
    )
    assert points(tree) == set()


def test_a_class_in_a_comment_is_not_measured(tree):
    root, web_src = tree
    _write(
        web_src, "views/form.js", "export class FormController {\n    save() {}\n}\n"
    )
    _write(
        root,
        "addons/sale/static/src/x.js",
        'import { FormController } from "@web/views/form";\n'
        "/*\nexport class Ghost extends FormController {\n    save() {}\n}\n*/\n",
    )
    assert points(tree) == set()


def test_an_inheritance_cycle_terminates(tree):
    # A malformed tree must not hang the gate.
    root, _web_src = tree
    _write(
        root,
        "addons/sale/static/src/x.js",
        'import { B } from "@sale/y";\nexport class A extends B {}\n',
    )
    _write(
        root,
        "addons/sale/static/src/y.js",
        'import { A } from "@sale/x";\nexport class B extends A {}\n',
    )
    assert points(tree) == set()


# --- provenance and drift ---


def test_provenance_records_the_scope_that_overrides(tree):
    root, web_src = tree
    _write(
        web_src, "views/form.js", "export class FormController {\n    save() {}\n}\n"
    )
    _write(
        root,
        "addons/sale/static/src/x.js",
        'import { FormController } from "@web/views/form";\n'
        "export class SaleForm extends FormController {\n    save() {}\n}\n",
    )
    detailed = jes.measure_detailed((("odoo", root),), web_src=web_src)
    assert jes.provenance(detailed) == {"FormController.save": frozenset({"odoo"})}


def test_a_point_new_to_a_scope_is_drift():
    measured = {"A.m": frozenset({"odoo"})}
    new, gone = jes.drift(measured, {}, ["odoo"])
    assert new == {"odoo": ["A.m"]} and gone == {}


def test_a_point_no_longer_overridden_is_drift_too():
    """Shrink-only in both directions — surface given up must be recorded."""
    new, gone = jes.drift({}, {"A.m": frozenset({"odoo"})}, ["odoo"])
    assert gone == {"odoo": ["A.m"]} and new == {}


def test_an_absent_scope_is_not_judged():
    """Repo-alone CI must be passable: enterprise-only pins are not drift there."""
    pinned = {"A.m": frozenset({"enterprise"})}
    new, gone = jes.drift({}, pinned, ["odoo"])
    assert new == {} and gone == {}


def test_a_tagless_pin_line_counts_for_every_scope():
    new, gone = jes.drift({"A.m": frozenset({"odoo"})}, {"A.m": frozenset()}, ["odoo"])
    assert new == {} and gone == {}


def test_a_pin_naming_a_vanished_method_is_reported(tree):
    """A rename inside web orphans its pin; without this the entry describes a
    contract that no longer exists and nothing ever says so."""
    _root, web_src = tree
    _write(
        web_src, "views/form.js", "export class FormController {\n    save() {}\n}\n"
    )
    assert jes.unresolved(["FormController.save"], web_src=web_src) == []
    assert jes.unresolved(["FormController.gone"], web_src=web_src) == [
        "FormController.gone"
    ]
    assert jes.unresolved(["Nonexistent.save"], web_src=web_src) == ["Nonexistent.save"]


# --- patch(): the other mechanism, same contract ---


def test_a_prototype_patch_is_an_override_point(tree):
    """`patch` depends on the same member as `extends`, and fails worse.

    Rename the member in `web` and the patch silently stops applying — a patch
    matching nothing looks exactly like one that has not run yet, so there is no
    error to notice.
    """
    root, web_src = tree
    _write(
        web_src,
        "webclient/navbar.js",
        "export class NavBar {\n    systrayItems() {}\n}\n",
    )
    _write(
        root,
        "addons/website/static/src/nav.js",
        'import { patch } from "@web/core/utils/patch";\n'
        'import { NavBar } from "@web/webclient/navbar";\n'
        "patch(NavBar.prototype, {\n    systrayItems() {},\n});\n",
    )
    assert points(tree) == {"NavBar.systrayItems"}


def test_a_bare_target_patch_counts_too(tree):
    root, web_src = tree
    _write(web_src, "a.js", "export class Thing {\n    go() {}\n}\n")
    _write(
        root,
        "addons/x/static/src/p.js",
        'import { Thing } from "@web/a";\npatch(Thing, {\n    go() {},\n});\n',
    )
    assert points(tree) == {"Thing.go"}


def test_a_patch_adding_a_member_the_base_lacks_is_not_a_point(tree):
    """Same rule as `extends`: adding behaviour is not depending on a contract."""
    root, web_src = tree
    _write(web_src, "a.js", "export class Thing {\n    go() {}\n}\n")
    _write(
        root,
        "addons/x/static/src/p.js",
        'import { Thing } from "@web/a";\npatch(Thing.prototype, {\n    brandNew() {},\n});\n',
    )
    assert points(tree) == set()


def test_a_patch_on_a_non_web_target_is_ignored(tree):
    root, web_src = tree
    _write(web_src, "a.js", "export class Thing {\n    go() {}\n}\n")
    _write(
        root,
        "addons/x/static/src/local.js",
        "class Local {\n    go() {}\n}\npatch(Local.prototype, {\n    go() {},\n});\n",
    )
    assert points(tree) == set()


def test_a_nested_object_literal_inside_a_patch_is_not_a_member(tree):
    """Depth-1 keys only.

    An object literal returned from a patched method has the same shape as the
    patch body; an indentation-based scan cannot tell them apart and would
    invent members from whatever the method happens to return.
    """
    root, web_src = tree
    _write(web_src, "a.js", "export class Thing {\n    go() {}\n    stay() {}\n}\n")
    _write(
        root,
        "addons/x/static/src/p.js",
        'import { Thing } from "@web/a";\n'
        "patch(Thing.prototype, {\n"
        "    go() {\n        return { stay: 1, other: 2 };\n    },\n"
        "});\n",
    )
    assert points(tree) == {"Thing.go"}


def test_patch_and_extends_land_on_one_key(tree):
    """Merged deliberately: the pin answers "depended on from outside", not
    "by which syntax"."""
    root, web_src = tree
    _write(web_src, "a.js", "export class Thing {\n    go() {}\n}\n")
    _write(
        root,
        "addons/x/static/src/sub.js",
        'import { Thing } from "@web/a";\n'
        "export class Sub extends Thing {\n    go() {}\n}\n",
    )
    _write(
        root,
        "addons/y/static/src/p.js",
        'import { Thing } from "@web/a";\npatch(Thing.prototype, {\n    go() {},\n});\n',
    )
    detailed = jes.measure_detailed((root,), web_src=web_src)
    assert set(detailed) == {"Thing.go"}
    assert sum(sum(counts) for counts in detailed["Thing.go"].values()) == 2


# --- --explain: the pin is a worklist, not just a count ---


def test_explain_names_the_overriding_files(tree):
    root, web_src = tree
    _write(
        web_src, "views/form.js", "export class FormController {\n    save() {}\n}\n"
    )
    _write(
        root,
        "addons/sale/static/src/x.js",
        'import { FormController } from "@web/views/form";\n'
        "export class SaleForm extends FormController {\n    save() {}\n}\n",
    )
    rows = jes.overriders("FormController.save", (root,), web_src=web_src)
    assert [(scope, subclass) for scope, _path, subclass in rows] == [
        (root.name, "SaleForm")
    ]


def test_explain_does_not_confuse_a_same_named_method_on_another_base(tree):
    """The reason this exists rather than a grep.

    ``_reset`` is declared by ``signature_pad`` and ``socket_io`` as well as by
    ``SearchModel``; a textual search answers the wrong question. Only the
    resolved chain can say which ``_reset`` a subclass overrides.
    """
    root, web_src = tree
    _write(web_src, "search.js", "export class SearchModel {\n    _reset() {}\n}\n")
    _write(
        root,
        "addons/a/static/src/unrelated.js",
        "export class SignaturePad {\n    _reset() {}\n}\n",
    )
    _write(
        root,
        "addons/b/static/src/real.js",
        'import { SearchModel } from "@web/search";\n'
        "export class RealSearch extends SearchModel {\n    _reset() {}\n}\n",
    )
    rows = jes.overriders("SearchModel._reset", (root,), web_src=web_src)
    assert [subclass for _s, _p, subclass in rows] == ["RealSearch"]


# --- the real tree: a measurement gate must find its inputs ---


def test_the_real_scan_reaches_the_tree():
    detailed = jes.measure_detailed()
    assert detailed, "measured nothing — the scan reached no consumer"
    assert len(detailed) > 100, f"implausibly small surface: {len(detailed)}"


def test_every_pinned_point_names_a_method_web_still_declares():
    """A stale pin silences nothing while looking like it does."""
    orphaned = jes.unresolved(jes.load_pinned())
    assert not orphaned, (
        f"{len(orphaned)} pinned point(s) name a method no web class declares: "
        f"{orphaned[:10]}\n  regenerate with --update after an intentional rename"
    )


def test_the_pin_matches_the_tree():
    present = [name for name, _ in jes._named_roots(jes.CONSUMER_ROOTS)]
    new, gone = jes.drift(
        jes.provenance(jes.measure_detailed()), jes.load_pinned(), present
    )
    assert not new and not gone, (
        f"extension surface drifted: new={new}, gone={gone}\n"
        "  python tooling/architecture/js_extension_surface.py --update"
    )


def test_the_docstring_measurements_are_fresh():
    import doc_measured

    problems = doc_measured.check(Path(jes.__file__), jes.repo_metrics())
    assert not problems, "\n".join(problems) + (
        "\n\n  python tooling/architecture/js_extension_surface.py --update-doc"
    )
