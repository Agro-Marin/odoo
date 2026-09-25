import logging
import re
from types import SimpleNamespace

from lxml import etree

from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry
from odoo.tests import tagged
from odoo.tests.common import BaseCase, get_db_name
from odoo.tools.view_ir import Node, from_arch

from .lint_case import LintCase

_logger = logging.getLogger(__name__)

_PARSER = etree.XMLParser(remove_comments=True, strip_cdata=False)


@tagged("post_install", "-at_install")
class OrphanLabelLinter(LintCase):
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
    def _rendered(cls, el) -> bool:
        return not any(
            node.get("invisible") in cls.LITERAL_INVISIBLE
            for node in (el, *el.iterancestors())
        )

    # Mirrors FormCompiler.compileLabel / compileField: a literal-invisible node
    # is never compiled, a label waits for the next compiled field whose `id`
    # (else `name`) it names, and binds at once to one already compiled.
    @classmethod
    def _orphans(cls, view, arch):
        present, buttons, compiled = set(), set(), set()
        pending: dict[str, int] = {}
        for el in arch.iter("field", "button", "label"):
            if el.tag == "button":
                if el.get("name"):
                    buttons.add(el.get("name"))
                continue
            if el.tag == "field":
                if not (name := el.get("name")):
                    continue
                key = el.get("id") or name
                present.update((name, key))
                if cls._rendered(el):
                    pending.pop(key, None)
                    compiled.update((name, key))
                continue
            target = el.get("for")
            if not target or target in compiled or not cls._rendered(el):
                continue
            if el.get("string") is not None or (el.text or "").strip():
                continue
            pending[target] = pending.get(target, 0) + 1
        for target, count in pending.items():
            if target in buttons:
                continue
            why = "absent" if target not in present else 'invisible="1"'
            finding = f"{view.xml_id or view.id}: <label for={target!r}> ({why})"
            yield from [finding] * count


class TestOrphanLabelBinding(BaseCase):
    def _orphans(self, arch: str) -> list[str]:
        view = SimpleNamespace(xml_id="m.v", id=1)
        return list(OrphanLabelLinter._orphans(view, etree.fromstring(arch)))

    def test_a_label_for_a_field_id_binds_to_that_field(self):
        self.assertEqual(
            self._orphans(
                '<form><label for="mail_box"/><field name="email" id="mail_box"/></form>'
            ),
            [],
        )

    def test_a_label_binds_to_the_next_rendered_field_of_its_name(self):
        self.assertEqual(
            self._orphans(
                "<form>"
                '<label for="pricelist_id"/><div><field name="pricelist_id"/></div>'
                '<field name="pricelist_id" invisible="1"/>'
                "</form>"
            ),
            [],
        )

    def test_a_label_whose_field_is_never_rendered_is_empty(self):
        self.assertEqual(
            self._orphans(
                "<form>"
                '<label for="a"/><field name="a" invisible="1"/>'
                '<label for="b"/><group invisible="1"><field name="b"/></group>'
                '<label for="c"/>'
                "</form>"
            ),
            [
                "m.v: <label for='a'> (invisible=\"1\")",
                "m.v: <label for='b'> (invisible=\"1\")",
                "m.v: <label for='c'> (absent)",
            ],
        )

    def test_a_label_that_is_not_rendered_itself_is_not_empty(self):
        self.assertEqual(
            self._orphans('<form><group invisible="1"><label for="a"/></group></form>'),
            [],
        )


@tagged("post_install", "-at_install")
class ActWindowViewOrderLinter(LintCase):
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
                continue
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

        from .lint_case import is_core_path

        return [
            manifest
            for manifest in Manifest.get_all_addon_manifests()
            if is_core_path(str(manifest.path))
        ]

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


# The form compiler builds these from `el.children`, which holds elements only:
# a text node directly inside one is never rendered, yet it is exported for
# translation. `page` only as a notebook's child and the button box only when it
# has an element child; `app` and `block` only under the settings compiler.
_FORM_TEXT_DROPPING = frozenset({"setting", "group", "notebook"})
_SETTINGS_TEXT_DROPPING = frozenset({"app", "block"})
_SETTINGS_JS_CLASS = "base_settings"


def _drops_text(node: Node, parent: Node | None, settings: bool) -> bool:
    if node.kind in _FORM_TEXT_DROPPING:
        return True
    if node.kind == "page":
        return parent is not None and parent.kind == "notebook"
    if node.kind == "div" and node.attrs.get("name") == "button_box":
        return any(not child.is_markup for child in node.children)
    return settings and node.kind in _SETTINGS_TEXT_DROPPING


def dropped_text(root: Node):
    settings = root.attrs.get("js_class") == _SETTINGS_JS_CLASS
    stack: list[tuple[Node, Node | None]] = [(root, None)]
    while stack:
        node, parent = stack.pop()
        stack.extend((child, node) for child in reversed(node.children))
        if not _drops_text(node, parent, settings):
            continue
        if (node.text or "").strip():
            yield node, node, node.text.strip()
        for child in node.children:
            if (child.tail or "").strip():
                yield node, child, child.tail.strip()


def _describe(node: Node) -> str:
    for attr in ("id", "name", "string", "title"):
        if node.attrs.get(attr):
            return f"<{node.kind} {attr}={node.attrs[attr]!r}>"
    return f"<{node.kind}>"


@tagged("post_install", "-at_install")
class DroppedViewTextLinter(LintCase):
    def test_no_form_text_goes_unrendered(self):
        offenders = set()
        with Registry(get_db_name()).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            View = env["ir.ui.view"]
            views = View.search([("type", "=", "form"), ("mode", "=", "primary")])
            self.assertTrue(views, "the scan reached no form views at all")
            found = []
            for root, hierarchy in views._get_hierarchies():
                try:
                    arch, combined = root._combine_tree(hierarchy)
                except Exception:
                    _logger.info(
                        "skipping %s: its arch does not combine",
                        root.xml_id or root.id,
                    )
                    continue
                for container, carrier, text in dropped_text(
                    combined if combined is not None else from_arch(arch)
                ):
                    origin = carrier.origin or container.origin
                    view_id = int(origin.split(",")[1]) if origin else root.id
                    where = _describe(container)
                    if carrier is not container:
                        where += f" after {_describe(carrier)}"
                    found.append((view_id, where, text))
            names = {
                view.id: view.xml_id or f"ir.ui.view({view.id})"
                for view in View.browse({view_id for view_id, _, _ in found})
            }
            offenders = {
                f"{names[view_id]}: {where} {text!r}" for view_id, where, text in found
            }
        self.assert_ratchet(
            offenders,
            "view_dropped_text",
            "text node(s) directly inside a form container that renders only "
            "its child elements",
            "The form compiler never renders them, and they are still exported "
            "for translation. Delete a stray one; wrap one meant to be read in "
            "an element (<span>, <div>) so it renders.",
        )


class TestDroppedViewText(BaseCase):
    def _found(self, arch: str) -> list[tuple[str, str]]:
        return [
            (container.kind, text)
            for container, _carrier, text in dropped_text(
                from_arch(etree.fromstring(arch))
            )
        ]

    def test_text_directly_inside_a_setting_is_found_before_and_after_its_field(self):
        self.assertEqual(
            self._found(
                '<form><setting string="s">a<field name="x"/> bytes</setting></form>'
            ),
            [("setting", "a"), ("setting", "bytes")],
        )

    def test_text_an_element_carries_inside_a_setting_is_rendered(self):
        self.assertEqual(
            self._found(
                "<form><setting>"
                '<field name="x"/><span>bytes</span><div>shown <b>too</b></div>'
                "</setting></form>"
            ),
            [],
        )

    def test_group_notebook_page_and_button_box_drop_their_direct_text(self):
        self.assertEqual(
            self._found(
                "<form><sheet>"
                '<div name="button_box">b<button name="x" type="object"/></div>'
                '<group>g<field name="x"/></group>'
                '<notebook>n<page string="p">p<field name="y"/></page></notebook>'
                "</sheet></form>"
            ),
            [("div", "b"), ("group", "g"), ("notebook", "n"), ("page", "p")],
        )

    def test_a_button_box_without_elements_and_a_page_outside_a_notebook_render(self):
        self.assertEqual(
            self._found(
                '<form><div name="button_box">empty</div><page>loose</page></form>'
            ),
            [],
        )

    def test_app_and_block_drop_text_only_under_the_settings_compiler(self):
        arch = '<form{}><app name="a">x<block title="b">y</block></app></form>'
        self.assertEqual(self._found(arch.format("")), [])
        self.assertEqual(
            self._found(arch.format(' js_class="base_settings"')),
            [("app", "x"), ("block", "y")],
        )

    def test_whitespace_and_a_comment_tail_of_whitespace_are_not_text(self):
        self.assertEqual(
            self._found(
                '<form><setting>\n  <!-- c -->\n  <field name="x"/>\n</setting></form>'
            ),
            [],
        )
