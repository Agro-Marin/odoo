from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestKpiProvider(TransactionCase):
    def test_kpi_summary(self):
        folder_inbox = self.env.ref("document.document_inbox_folder")
        other_folder = self.env.ref("document.document_finance_folder")

        # Clean things for the test
        self.env["document.document"].search(
            [
                ("folder_id", "=", folder_inbox.id),
            ]
        ).folder_id = other_folder
        self.assertCountEqual(
            self.env["kpi.provider"].get_documents_kpi_summary(),
            [{"id": "document.inbox", "name": "Inbox", "type": "integer", "value": 0}],
        )

        # the KPI figure reflects the amount of documents in the inbox folder
        all_documents = self.env["document.document"].create(
            [
                {
                    "name": "Test Document",
                    "folder_id": folder_inbox.id,
                }
            ]
            * 2
        )
        self.assertCountEqual(
            self.env["kpi.provider"].get_documents_kpi_summary(),
            [{"id": "document.inbox", "name": "Inbox", "type": "integer", "value": 2}],
        )

        # if a document is moved out of the folder, it changes the KPI figure
        all_documents[0].folder_id = other_folder
        self.assertCountEqual(
            self.env["kpi.provider"].get_documents_kpi_summary(),
            [{"id": "document.inbox", "name": "Inbox", "type": "integer", "value": 1}],
        )

        # if the folder is archived, don't show the KPI category at all
        folder_inbox.action_archive()
        self.assertCountEqual(self.env["kpi.provider"].get_documents_kpi_summary(), [])

        # if the folder is not present at all, don't show the KPI category at all
        folder_inbox.action_unarchive()
        all_documents.folder_id = other_folder  # folder must be empty to be unlinkable
        folder_inbox.unlink()
        self.assertCountEqual(self.env["kpi.provider"].get_documents_kpi_summary(), [])
