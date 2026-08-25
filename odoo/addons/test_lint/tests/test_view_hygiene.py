import logging
import re

from lxml import etree

from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry
from odoo.tests import tagged
from odoo.tests.common import get_db_name

from .lint_case import LintCase, core_data_files

_logger = logging.getLogger(__name__)

_PARSER = etree.XMLParser(remove_comments=True, strip_cdata=False)

# `optional` is read by list_optional_fields.js, which decides a column's initial
# visibility with `col.optional === "show"` -- so every value that is not "show"
# hides the column, and a typo such as optional="hidden" works by accident. The
# renderer therefore cannot tell a mistake from an intention; this gate can.
# "conditional" is account's extension, honoured by
# product_label_section_and_note_field_o2m.js.
OPTIONAL_VALUES = frozenset({"show", "hide", "conditional"})

# A kanban <templates> block is compiled one `t-name` at a time:
# compileViewTemplates() calls App.registerTemplate() per name, so each becomes an
# independent OWL template with its own scope. A `t-set` in one therefore does NOT
# reach another -- and OWL resolves the missing name to undefined rather than
# raising, so the markup that reads it silently never renders.
#
# Only the entry points are compiled that way. Every other `t-name` in the block is
# reached through `t-call`, which DOES inherit the caller's scope, so a variable
# set by the caller is legitimately visible there.
KANBAN_ENTRY_TEMPLATES = frozenset({"card", "menu"})

_BARE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@tagged("post_install", "-at_install")
class ViewHygieneLinter(LintCase):
    """Static view-arch checks whose failure mode is silence.

    Each rule here is one that the runtime does not complain about: a column
    quietly hidden, markup quietly never rendered, an attribute quietly never
    read. A linter is the only thing that can see them.
    """

    @staticmethod
    def scanned_files():
        return core_data_files()

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.optional_violations = []
        cls.kanban_scope_violations = []
        cls.groupby_domain_violations = []
        cls.checked = 0
        for path in cls.scanned_files():
            try:
                tree = etree.parse(str(path), _PARSER)
            except etree.XMLSyntaxError:
                continue  # test fixtures are deliberately malformed; not our business
            cls.checked += 1
            cls.optional_violations.extend(cls._optional(path, tree))
            cls.kanban_scope_violations.extend(cls._kanban_scope(path, tree))
            cls.groupby_domain_violations.extend(cls._groupby_domain(path, tree))
        _logger.info("parsed %s XML data files once for three checks", cls.checked)

    def _assert_none(self, violations, what, fix):
        self.assertTrue(self.checked, "the scan reached no XML files at all")
        if violations:
            self.fail(
                f"{len(violations)} {what}. {fix}\n"
                + "\n".join(f"  {v}" for v in sorted(violations)[:200])
                + (
                    f"\n  ... and {len(violations) - 200} more"
                    if len(violations) > 200
                    else ""
                )
            )

    def test_optional_attribute_vocabulary(self):
        self._assert_none(
            self.optional_violations,
            "field(s) with an `optional` value the list renderer does not know",
            'Use optional="show" or optional="hide". Any other value hides the '
            'column, but only because the renderer compares against "show".',
        )

    def test_kanban_template_scope(self):
        self._assert_none(
            self.kanban_scope_violations,
            "kanban entry template(s) reading a variable set in a sibling template",
            "Each `t-name` in a kanban <templates> is its own OWL template. Repeat "
            "the `t-set`, or inline the expression -- OWL resolves the missing name "
            "to undefined, so the markup never renders and nothing reports it.",
        )

    def test_groupby_filter_carries_no_domain(self):
        self._assert_none(
            self.groupby_domain_violations,
            'group-by <filter>(s) carrying a redundant domain="[]"',
            "Drop the attribute. classifyByContext() promotes a filter whose context "
            "sets group_by to a `groupBy` item, and visitFilter() reads `domain` only "
            "while the item is still a `filter`, so it is never used.",
        )

    @staticmethod
    def _optional(path, tree):
        for el in tree.iter():
            value = el.get("optional")
            if value is not None and value not in OPTIONAL_VALUES:
                yield f"{path}:{el.sourceline} optional={value!r}"

    @classmethod
    def _kanban_scope(cls, path, tree):
        for kanban in tree.iter("kanban"):
            for templates in kanban.iter("templates"):
                named = {
                    tpl.get("t-name"): tpl for tpl in templates if tpl.get("t-name")
                }
                if len(named) < 2:
                    continue
                assigned = {
                    name: {n.get("t-set") for n in tpl.iter() if n.get("t-set")}
                    for name, tpl in named.items()
                }
                for name, tpl in named.items():
                    if name not in KANBAN_ENTRY_TEMPLATES:
                        continue  # only reachable via t-call, which inherits scope
                    elsewhere = set().union(
                        *(names for key, names in assigned.items() if key != name)
                    )
                    leaked = elsewhere - assigned[name]
                    for node in tpl.iter():
                        expr = (node.get("t-if") or "").strip()
                        if _BARE_NAME.match(expr) and expr in leaked:
                            yield (
                                f"{path}:{node.sourceline} <{node.tag} t-if={expr!r}> "
                                f"in t-name={name!r}, set only in "
                                f"{sorted(k for k, v in assigned.items() if expr in v)}"
                            )

    @staticmethod
    def _groupby_domain(path, tree):
        for el in tree.iter("filter"):
            if el.get("domain") != "[]":
                continue
            if "group_by" in (el.get("context") or ""):
                yield f"{path}:{el.sourceline} <filter name={el.get('name')!r}>"


@tagged("post_install", "-at_install")
class OrphanLabelLinter(LintCase):
    """No `<label for="X">` may render empty because X was compiled away.

    ViewCompiler.compileNode drops a node whose `invisible` is the *literal* "1"
    or "True" before compileField runs, so `encounteredFields[X]` is never set and
    compileLabel falls through to its raw-element branch. createLabelFromField --
    the only place a label inherits its field's string and modifiers -- never runs,
    and the server-side postprocess only narrows model groups. The result is a
    literal `<label></label>` and a `for` pointing at nothing.

    A label that carries its own `string` (or text) is a different, deliberate
    idiom: a heading beside a field kept invisible purely to feed sibling
    expressions. Only the ones with no content of their own are defects, because
    only they lose everything they had to say.

    This reads combined archs, so it needs the registry: the label and the field
    it names usually live in different modules.
    """

    LITERAL_INVISIBLE = frozenset({"1", "True"})

    def test_no_label_renders_empty(self):
        offenders = []
        with Registry(get_db_name()).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            views = env["ir.ui.view"].search([("type", "not in", ("qweb", "search"))])
            self.assertTrue(views, "the scan reached no views at all")
            for view in views:
                try:
                    arch = view._get_combined_arch()
                except Exception:
                    # A view that will not combine is another gate's finding, not
                    # this one's; say so rather than swallowing it.
                    _logger.info(
                        "skipping %s: its arch does not combine",
                        view.xml_id or view.id,
                    )
                    continue
                if not etree.iselement(arch):
                    arch = etree.fromstring(arch)
                offenders.extend(self._orphans(view, arch))
        if offenders:
            self.fail(
                f"{len(offenders)} <label for=...> that render(s) empty:\n"
                + "\n".join(f"  {o}" for o in sorted(offenders))
                + "\n\nRemove the label with the field it names (or give the label "
                'its own string). Hiding a field with invisible="1" removes it '
                "from the compiled tree, and its label goes silently empty."
            )

    @classmethod
    def _orphans(cls, view, arch):
        dropped, present = set(), set()
        for el in arch.iter("field"):
            name = el.get("name")
            if not name:
                continue
            present.add(name)
            if el.get("invisible") in cls.LITERAL_INVISIBLE:
                dropped.add(name)
            else:
                dropped.discard(name)  # a visible occurrence survives compilation
        for el in arch.iter("button"):
            if el.get("name"):
                present.add(el.get("name"))
        for el in arch.iter("label"):
            target = el.get("for")
            if not target or (target in present and target not in dropped):
                continue
            if el.get("string") is not None or (el.text or "").strip():
                continue  # carries its own text; only the `for` is inert
            why = "absent" if target not in present else 'invisible="1"'
            yield f"{view.xml_id or view.id}: <label for={target!r}> ({why})"


@tagged("post_install", "-at_install")
class ActWindowViewOrderLinter(LintCase):
    """An explicit `view_mode` must name the view the action actually opens on.

    `_compute_views` emits the pinned views first -- `view_ids` sorted by
    sequence, then `view_id` -- and only then the `view_mode` modes it has not
    already covered. So `view_mode` is not the order; it degrades into a set the
    moment an action pins anything, and the file can say `list,form` while the
    action opens on a form. Nothing warns, and 22 declarations in this tree had
    drifted that way.

    Two consequences make it worth a gate rather than a comment. The order is
    load-bearing in a way the syntax hides: *removing* a pinned row can change
    which view opens, because with a `form` row in `view_ids` a `view_id` of type
    `list` can no longer hold `list` first -- that is how
    `base.action_res_users_view1`, which reads as redundant, turns out to be the
    only thing keeping the Users menu off the form view. And an action that pins
    nothing is not lying: it never claimed an order, so `view_mode`'s default is
    not contradicted and there is nothing here to report.

    Resolved from the tree rather than the registry on purpose: at test_lint's
    scope only test_lint is installed, so a registry check would see almost
    nothing. Validated against a 25-module registry -- every mismatch the
    registry reported within this scope is reported here, plus eleven more in
    modules that install did not include.
    """

    # A pin is written either as separate ir.actions.act_window.view records or
    # inline as view_ids="[(5,0,0),(0,0,{'view_mode': ...})]". Both spellings are
    # in use (91 actions and 64 actions respectively), and a checker that knew
    # only the first missed a third of them.
    _MODE_IN_EVAL = re.compile(r"['\"]view_mode['\"]\s*:\s*['\"](\w+)['\"]")

    def test_view_mode_names_the_view_that_opens(self):
        declared, pins, inline, view_id_ref, view_type, where = {}, {}, {}, {}, {}, {}
        for manifest in self._manifests_in_scope():
            for path in self._data_files(manifest):
                tree = self._parse(path)
                if tree is None:
                    continue
                self._collect(
                    manifest.name,
                    path,
                    tree,
                    declared,
                    pins,
                    inline,
                    view_id_ref,
                    view_type,
                    where,
                )

        offenders = []
        for xmlid, modes in declared.items():
            pinned = inline.get(xmlid) or [m for _, m in sorted(pins.get(xmlid, []))]
            if not pinned:
                continue  # claims nothing beyond the mode list itself
            effective = list(pinned)
            missing = [m for m in modes if m not in set(pinned)]
            pinned_type = view_type.get(view_id_ref.get(xmlid))
            if pinned_type and pinned_type in missing:
                missing.remove(pinned_type)
                effective.append(pinned_type)
            effective.extend(missing)
            if effective and effective[0] != modes[0]:
                path, line = where[xmlid]
                offenders.append(
                    f"{path}:{line} {xmlid}: view_mode says {modes[0]!r} opens first, "
                    f"{effective[0]!r} does ({','.join(modes)} -> {','.join(effective)})"
                )
        self.assertTrue(declared, "the scan reached no act_window declarations")
        if offenders:
            self.fail(
                f"{len(offenders)} act_window(s) whose view_mode does not name the "
                f"view that opens:\n"
                + "\n".join(f"  {o}" for o in sorted(offenders))
                + "\n\nReorder view_mode to match. Doing so cannot change behaviour: "
                "the pinned prefix is untouched and the remaining modes keep their "
                "relative order, so the merge is a fixed point."
            )

    @staticmethod
    def _manifests_in_scope():
        from odoo.modules import Manifest

        return list(Manifest.all_addon_manifests())

    @staticmethod
    def _data_files(manifest):
        from pathlib import Path

        for rel in manifest.get("data") or []:
            if rel.endswith(".xml"):
                path = Path(manifest.path) / rel
                if path.exists():
                    yield path

    @staticmethod
    def _parse(path):
        try:
            return etree.parse(str(path), _PARSER)
        except etree.XMLSyntaxError:
            return None

    @classmethod
    def _collect(
        cls, module, path, tree, declared, pins, inline, view_id_ref, view_type, where
    ):
        def norm(ref):
            return ref if "." in ref else f"{module}.{ref}"

        for rec in tree.iter("record"):
            model, rec_id = rec.get("model"), rec.get("id")
            if not rec_id:
                continue
            xmlid = norm(rec_id)
            if model == "ir.ui.view":
                arch = rec.find("field[@name='arch']")
                if arch is not None and len(arch):
                    view_type[xmlid] = arch[0].tag
            elif model == "ir.actions.act_window":
                mode = rec.find("field[@name='view_mode']")
                if mode is not None and (mode.text or "").strip():
                    declared[xmlid] = [m for m in mode.text.strip().split(",") if m]
                    where[xmlid] = (path, mode.sourceline)
                ref = rec.find("field[@name='view_id']")
                if ref is not None and ref.get("ref"):
                    view_id_ref[xmlid] = norm(ref.get("ref"))
                many = rec.find("field[@name='view_ids']")
                if many is not None and many.get("eval"):
                    found = cls._MODE_IN_EVAL.findall(many.get("eval"))
                    if found:
                        inline[xmlid] = found
            elif model == "ir.actions.act_window.view":
                action = rec.find("field[@name='act_window_id']")
                mode = rec.find("field[@name='view_mode']")
                seq = rec.find("field[@name='sequence']")
                if action is None or not action.get("ref") or mode is None:
                    continue
                raw = (seq.get("eval") or (seq.text or "")) if seq is not None else "0"
                try:
                    order = int(str(raw).strip())
                except ValueError:
                    order = 0
                pins.setdefault(norm(action.get("ref")), []).append(
                    (order, (mode.text or "").strip())
                )
