import logging
import re

from lxml import etree

from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry
from odoo.tests import tagged
from odoo.tests.common import get_db_name

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
                dropped.discard(name)
        for el in arch.iter("button"):
            if el.get("name"):
                present.add(el.get("name"))
        for el in arch.iter("label"):
            target = el.get("for")
            if not target or (target in present and target not in dropped):
                continue
            if el.get("string") is not None or (el.text or "").strip():
                continue
            why = "absent" if target not in present else 'invisible="1"'
            yield f"{view.xml_id or view.id}: <label for={target!r}> ({why})"


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

        return list(Manifest.get_all_addon_manifests())

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
