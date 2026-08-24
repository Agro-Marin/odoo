"""The folder tree the client draws, and the groupings behind it.

Named for what it protects, not for the review that produced it.
"""

import pathlib
import re

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from .test_documents_common import TEXT, TransactionCaseDocuments


class TestDocumentsSearchPanelCounters(TransactionCase):

    def test_search_panel_counters_do_not_crash_and_roll_up(self):
        Document = self.env["documents.document"]
        parent = Document.create(
            {"name": "Counted parent", "type": "folder", "access_internal": "edit"}
        )
        child = Document.create(
            {
                "name": "Counted child",
                "type": "folder",
                "folder_id": parent.id,
                "access_internal": "edit",
            }
        )
        Document.create(
            [
                {"name": "direct", "type": "binary", "folder_id": parent.id},
                {"name": "nested a", "type": "binary", "folder_id": child.id},
                {"name": "nested b", "type": "binary", "folder_id": child.id},
            ]
        )

        result = Document.search_panel_select_range(
            "user_folder_id", enable_counters=True, search_domain=[]
        )
        counts = {
            value["id"]: value.get("__count")
            for value in result["values"]
            if isinstance(value["id"], int)
        }

        self.assertEqual(counts[child.id], 2, "a folder counts what it holds")
        self.assertEqual(
            counts[parent.id],
            4,
            "an ancestor counts its own items plus its descendants'",
        )

    def test_search_panel_counters_survive_a_parent_cycle(self):
        Document = self.env["documents.document"]
        first = Document.create({"name": "Cycle A", "type": "folder"})
        second = Document.create(
            {"name": "Cycle B", "type": "folder", "folder_id": first.id}
        )
        Document.create({"name": "in cycle", "type": "binary", "folder_id": second.id})
        self.env.cr.execute(
            "UPDATE documents_document SET folder_id = %s WHERE id = %s",
            (second.id, first.id),
        )
        first.invalidate_recordset()

        result = Document.search_panel_select_range(
            "user_folder_id", enable_counters=True, search_domain=[]
        )

        self.assertTrue(result["values"], "the panel must still render")


@tagged("post_install", "-at_install")
class TestDocumentsLastAccessGrouping(TransactionCaseDocuments):
    def test_f5_last_access_date_group_not_stale(self):
        doc = self.document_gif
        access = doc.access_ids.filtered(
            lambda a: a.partner_id == self.doc_user.partner_id
        )
        self.assertTrue(access)
        access.last_access_date = fields.Datetime.now()
        self.assertEqual(doc.with_user(self.doc_user).last_access_date_group, "3_day")

        access.last_access_date = fields.Datetime.subtract(
            fields.Datetime.now(), days=400
        )
        self.assertEqual(
            doc.with_user(self.doc_user).last_access_date_group,
            "0_older",
            "last_access_date_group did not follow last_access_date",
        )

    def test_f5_last_access_date_group_is_per_user(self):
        doc = self.document_gif
        doc.action_update_access_rights(
            partners={self.doc_user_2.partner_id.id: ("edit", False)}
        )
        access_1 = doc.access_ids.filtered(
            lambda a: a.partner_id == self.doc_user.partner_id
        )
        access_2 = doc.access_ids.filtered(
            lambda a: a.partner_id == self.doc_user_2.partner_id
        )
        access_1.last_access_date = fields.Datetime.now()
        access_2.last_access_date = fields.Datetime.subtract(
            fields.Datetime.now(), days=400
        )

        self.assertEqual(doc.with_user(self.doc_user).last_access_date_group, "3_day")
        self.assertEqual(
            doc.with_user(self.doc_user_2).last_access_date_group,
            "0_older",
            "last_access_date_group is shared between users (missing "
            "depends_context('uid'))",
        )


@tagged("post_install", "-at_install")
class TestDocumentsClientFieldLists(TransactionCase):
    """Field names the client spells out, checked against the model.

    Two lists in `static/` name server fields as strings, and a string does not
    break when the field it names moves. Both had already drifted: the mock's
    search-panel list had lost four fields the route sends, which made every
    client surface fed from a folder's search-panel data render empty in tests
    while working against the server -- a mock that disagrees quietly rather
    than failing.
    """

    def _read_js(self, relative_path):
        path = pathlib.Path(__file__).resolve().parent.parent / relative_path
        return path.read_text(encoding="utf-8")

    def _js_string_list(self, source, marker, label, which=0):
        """Return the strings of the *which*-th ``[...]`` literal after *marker*.

        `which` is needed because the call this reads takes a domain before its
        field list, and the domain is a bracketed literal too.
        """
        start = source.find(marker)
        self.assertNotEqual(
            start, -1, f"{label}: {marker!r} not found -- has it been renamed?"
        )
        groups, depth, opening = [], 0, None
        for index in range(start, len(source)):
            if source[index] == "[":
                if depth == 0:
                    opening = index
                depth += 1
            elif source[index] == "]":
                depth -= 1
                if depth == 0:
                    groups.append(source[opening : index + 1])
                    if len(groups) > which:
                        break
        self.assertGreater(
            len(groups), which, f"{label}: no list literal #{which} after {marker!r}"
        )
        return set(re.findall(r'"([a-z_0-9]+)"', groups[which]))

    def test_the_mock_search_panel_reads_what_the_route_sends(self):
        """The mock's field list must cover `_get_fields_search_panel()`.

        The mock may read *more* (it builds the folder tree itself, so it also
        wants `id`, `is_folder` and `type`); it may not read less, because what
        it leaves out simply arrives empty in every test that renders it.
        """
        source = self._read_js("static/tests/helpers/data.js")
        mock_fields = self._js_string_list(
            source,
            "async search_panel_select_range",
            "documents.document mock",
            # [0] is the `[["type", "=", "folder"]]` domain, [1] the field list
            which=1,
        )
        served = set(self.env["documents.document"]._get_fields_search_panel())
        self.assertFalse(
            served - mock_fields,
            "the search panel mock no longer reads every field the route "
            "sends; add them to `search_panel_select_range` in "
            "static/tests/helpers/data.js",
        )

    def test_the_details_panel_asks_for_fields_that_exist(self):
        """Every name in `DETAIL_PANEL_REQUIRED_FIELDS` must be a real field.

        The list is injected into `activeFields` for every documents view, and
        the web client dereferences the field definition while building the read
        specification -- so a name that no longer resolves is not a blank panel,
        it is a TypeError that takes the whole view's data loading down.
        """
        source = self._read_js("static/src/views/hooks.js")
        required = self._js_string_list(
            source, "DETAIL_PANEL_REQUIRED_FIELDS", "DETAIL_PANEL_REQUIRED_FIELDS"
        )
        self.assertTrue(required, "the list was parsed as empty")
        unknown = required - set(self.env["documents.document"]._fields)
        self.assertFalse(
            unknown,
            f"DETAIL_PANEL_REQUIRED_FIELDS names fields that do not exist: "
            f"{sorted(unknown)}",
        )


class TestDocumentsSearchPanelContract(TransactionCaseDocuments):
    def test_f9_user_folder_id_accepts_int(self):
        doc = self.env["documents.document"].create(
            {
                "type": "binary",
                "datas": TEXT,
                "name": "audit3 int folder.txt",
                "folder_id": self.folder_b.id,
                "owner_id": self.doc_user.id,
            }
        )
        doc.write({"user_folder_id": self.folder_a.id})
        self.assertEqual(doc.folder_id, self.folder_a)
        with self.assertRaises(UserError):
            doc.write({"user_folder_id": ["not", "a", "folder"]})

    def test_f9_search_panel_select_range_forwards_kwargs(self):
        result = self.env["documents.document"].search_panel_select_range(
            "folder_id", enable_counters=True
        )
        self.assertIn("values", result)

    def test_f9_search_filter_names_are_unique(self):
        view = self.env.ref("documents.document_view_search")
        arch = view.arch_db
        self.assertIn('name="my_drive_filter"', arch)
        self.assertIn('name="in_company_filter"', arch)
        self.assertEqual(arch.count('name="my_drive_filter"'), 1)
