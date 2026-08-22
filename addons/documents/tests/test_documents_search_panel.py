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
