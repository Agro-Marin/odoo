import base64
import io

from PIL import Image

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import tagged, users

from .test_documents_common import GIF, TEXT, TransactionCaseDocuments


def _png(color):
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), color).save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue())


@tagged("post_install", "-at_install")
class TestDocumentsPropagationDomain(TransactionCaseDocuments):

    def test_access_domain_layers_on_the_propagation_domain(self):
        calls = []
        DocumentsDocument = type(self.env["documents.document"])
        base_rule = DocumentsDocument._get_propagation_domain

        def spy(records):
            calls.append("propagation")
            return base_rule(records)

        self.patch(DocumentsDocument, "_get_propagation_domain", spy)
        self.env["documents.document"]._get_access_update_domain()
        self.assertTrue(
            calls,
            "_get_access_update_domain must layer on _get_propagation_domain, "
            "not restate the rule",
        )

    def test_company_propagation_uses_the_base_rule(self):
        company = self.env["res.company"].create({"name": "Dedup Co"})
        folder = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "prop root",
                "access_internal": "edit",
            }
        )
        child = self.env["documents.document"].create(
            {
                "type": "binary",
                "name": "prop child",
                "folder_id": folder.id,
                "access_internal": "edit",
            }
        )

        calls = []
        DocumentsDocument = type(self.env["documents.document"])
        base_rule = DocumentsDocument._get_propagation_domain

        def spy(records):
            calls.append("propagation")
            return base_rule(records)

        self.patch(DocumentsDocument, "_get_propagation_domain", spy)
        folder._update_company(company.id)
        self.assertTrue(
            calls, "_update_company must go through _get_propagation_domain"
        )
        child.invalidate_recordset()
        self.assertEqual(
            child.company_id, company, "company still propagates to children"
        )


@tagged("post_install", "-at_install")
class TestDocumentsArchiveWording(TransactionCaseDocuments):

    def test_single_source_for_the_denial_message(self):
        message = self.env["documents.document"]._archive_denied_message()
        self.assertTrue(message)
        document = self.env["documents.document"].create(
            {
                "type": "binary",
                "name": "not yours",
                "folder_id": self.folder_a.id,
                "owner_id": self.document_manager.id,
            }
        )
        with self.assertRaises(UserError) as caught:
            document.with_user(self.internal_user)._raise_if_unauthorized_archive()
        self.assertEqual(str(caught.exception), message)


@tagged("post_install", "-at_install")
class TestDocumentsUserPermissionContract(TransactionCaseDocuments):

    def test_user_permission_is_readable(self):
        document = self.env["documents.document"].create(
            {
                "type": "binary",
                "name": "readable",
                "folder_id": self.folder_a.id,
                "access_internal": "edit",
            }
        )
        self.assertIn(
            document.with_user(self.internal_user).user_permission,
            ("none", "view", "edit"),
        )

    def test_user_permission_is_readable_in_batch(self):
        documents = self.env["documents.document"].create(
            [
                {
                    "type": "binary",
                    "name": f"batch {index}",
                    "folder_id": self.folder_a.id,
                    "access_internal": "edit",
                }
                for index in range(3)
            ]
        )
        levels = documents.with_user(self.internal_user).mapped("user_permission")
        self.assertEqual(len(levels), 3)

    def test_search_side_agrees_with_the_read_side(self):
        document = self.env["documents.document"].create(
            {
                "type": "binary",
                "name": "agreeing",
                "folder_id": self.folder_a.id,
                "access_internal": "edit",
                "access_ids": [
                    Command.create(
                        {
                            "partner_id": self.internal_user.partner_id.id,
                            "role": "edit",
                        }
                    )
                ],
            }
        )
        as_user = document.with_user(self.internal_user)
        found = (
            self.env["documents.document"]
            .with_user(self.internal_user)
            .search(
                [
                    ("id", "=", document.id),
                    ("user_permission", "=", as_user.user_permission),
                ]
            )
        )
        self.assertEqual(found, document)


@tagged("post_install", "-at_install")
class TestDocumentsCreateAccessCommands(TransactionCaseDocuments):

    def setUp(self):
        super().setUp()
        self.member = self.env["res.partner"].create({"name": "hardening member"})
        self.host = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "hardening host",
                "owner_id": self.doc_user.id,
                "access_internal": "edit",
                "access_ids": [
                    Command.create({"partner_id": self.member.id, "role": "edit"})
                ],
            }
        )
        self.foreign = self.env["documents.access"].create(
            {
                "document_id": self.folder_a.id,
                "partner_id": self.member.id,
                "role": "view",
            }
        )

    def _create(self, access_ids):
        return self.env["documents.document"].create(
            {
                "type": "binary",
                "name": "hardening child",
                "datas": GIF,
                "folder_id": self.host.id,
                "access_ids": access_ids,
            }
        )

    def test_reparenting_commands_are_refused_cleanly(self):
        for label, commands in (
            ("link", [Command.link(self.foreign.id)]),
            ("set", [Command.set([self.foreign.id])]),
            ("raw set tuple", [(6, 0, [self.foreign.id])]),
            ("update", [Command.update(self.foreign.id, {"role": "edit"})]),
            ("unlink", [Command.unlink(self.foreign.id)]),
            ("delete", [Command.delete(self.foreign.id)]),
        ):
            with self.subTest(command=label), self.assertRaises(UserError):
                self._create(commands)

    def test_documented_opt_out_forms_still_opt_out(self):
        for label, commands in (
            ("False", False),
            ("empty list", []),
            ("Command.set([])", [Command.set([])]),
            ("raw empty set tuple", [(6, 0, [])]),
            ("Command.clear()", [Command.clear()]),
        ):
            with self.subTest(form=label):
                document = self._create(commands)
                self.assertNotIn(
                    self.member,
                    document.access_ids.filtered("role").partner_id,
                    "an explicit empty access_ids must not inherit the folder's",
                )

    def test_granting_a_member_still_inherits_the_folder(self):
        other = self.env["res.partner"].create({"name": "hardening other"})
        document = self._create(
            [Command.create({"partner_id": other.id, "role": "view"})]
        )
        self.assertEqual(
            document.access_ids.filtered("role").partner_id,
            other | self.member | self.host.owner_id.partner_id,
            "a CREATE grant adds to, it does not replace, folder inheritance",
        )

    def test_no_access_ids_inherits_the_folder(self):
        document = self.env["documents.document"].create(
            {
                "type": "binary",
                "name": "hardening default",
                "datas": GIF,
                "folder_id": self.host.id,
            }
        )
        self.assertIn(self.member, document.access_ids.filtered("role").partner_id)


@tagged("post_install", "-at_install")
class TestDocumentsReadCost(TransactionCaseDocuments):

    def test_search_read_of_folder_id_is_batched(self):
        count = 25
        documents = self.env["documents.document"].create(
            [
                {
                    "type": "binary",
                    "name": f"cost {index}",
                    "datas": GIF,
                    "folder_id": self.folder_b.id,
                    "owner_id": self.doc_user.id,
                }
                for index in range(count)
            ]
        )
        self.env.flush_all()
        Document = self.env["documents.document"].with_user(self.doc_user)
        self.env.invalidate_all()

        before = self.env.cr.sql_log_count
        result = Document.search_read([("id", "in", documents.ids)], ["folder_id"])
        queries = self.env.cr.sql_log_count - before

        self.assertEqual(len(result), count)
        self.assertTrue(all(row["folder_id"] for row in result))
        self.assertLess(
            queries,
            count,
            f"{queries} queries for {count} records is the per-record ACL check",
        )

    def test_batched_read_gives_the_same_answer_as_the_per_record_check(self):
        hidden = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "cost hidden",
                "owner_id": self.document_manager.id,
                "access_internal": "none",
                "access_via_link": "none",
            }
        )
        inside = self.env["documents.document"].create(
            [
                {
                    "type": "binary",
                    "name": f"cost hidden {index}",
                    "datas": GIF,
                    "folder_id": hidden.id,
                    "owner_id": self.doc_user.id,
                    "access_internal": "none",
                    "access_via_link": "none",
                    "access_ids": False,
                }
                for index in range(3)
            ]
        )
        self.env.flush_all()
        self.env.invalidate_all()
        rows = inside.with_user(self.doc_user).read(["folder_id"])
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertFalse(
                row["folder_id"],
                "a folder the reader cannot see must stay hidden in the m2o",
            )


@tagged("post_install", "-at_install")
class TestDocumentsPermissionSingleSource(TransactionCaseDocuments):

    def test_link_inherited_from_the_parent_is_the_only_difference(self):
        parent = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "single source parent",
                "owner_id": self.document_manager.id,
                "access_internal": "view",
            }
        )
        child = self.env["documents.document"].create(
            {
                "type": "binary",
                "name": "single source child",
                "datas": GIF,
                "folder_id": parent.id,
                "owner_id": self.document_manager.id,
                "access_internal": "none",
                "access_via_link": "view",
                "is_access_via_link_hidden": False,
            }
        )
        self.env.flush_all()
        as_user = child.with_user(self.internal_user)
        self.assertEqual(
            as_user.user_permission,
            "view",
            "the parent is reachable, so the child's link grants view",
        )
        self.assertEqual(
            as_user._get_permission_without_token(),
            "none",
            "and without the link there is nothing left -- which is the point",
        )

    def test_membership_agrees_with_the_domain(self):
        document = self.env["documents.document"].create(
            {
                "type": "binary",
                "name": "single source member",
                "datas": GIF,
                "owner_id": self.document_manager.id,
                "access_internal": "none",
                "access_via_link": "none",
                "access_ids": [
                    Command.create(
                        {"partner_id": self.internal_user.partner_id.id, "role": "edit"}
                    )
                ],
            }
        )
        self.env.flush_all()
        as_user = document.with_user(self.internal_user)
        self.assertEqual(as_user.user_permission, "edit")
        self.assertEqual(as_user._get_permission_without_token(), "edit")

    def test_ownership_agrees_with_the_domain(self):
        document = self.env["documents.document"].create(
            {
                "type": "binary",
                "name": "single source owned",
                "datas": GIF,
                "owner_id": self.internal_user.id,
                "access_internal": "none",
                "access_via_link": "none",
            }
        )
        self.env.flush_all()
        as_user = document.with_user(self.internal_user)
        self.assertEqual(as_user.user_permission, "edit")
        self.assertEqual(as_user._get_permission_without_token(), "edit")

    def test_unreachable_document_is_none_both_ways(self):
        document = self.env["documents.document"].create(
            {
                "type": "binary",
                "name": "single source hidden",
                "datas": GIF,
                "owner_id": self.document_manager.id,
                "access_internal": "none",
                "access_via_link": "none",
                "access_ids": False,
            }
        )
        self.env.flush_all()
        as_user = document.with_user(self.internal_user)
        self.assertEqual(as_user.sudo(False).user_permission, "none")
        self.assertEqual(as_user._get_permission_without_token(), "none")


@tagged("post_install", "-at_install")
class TestDocumentsAccessErrorSurface(TransactionCaseDocuments):
    def test_access_row_cannot_be_written_without_edit_on_the_document(self):
        access = self.env["documents.access"].create(
            {
                "document_id": self.company_root_folder.id,
                "partner_id": self.internal_user.partner_id.id,
                "role": "view",
            }
        )
        with self.assertRaises(AccessError):
            access.with_user(self.internal_user).write({"role": "edit"})


@tagged("post_install", "-at_install")
class TestDocumentsMoveAuthorization(TransactionCaseDocuments):
    def test_f1_move_to_root_is_guarded(self):
        doc = self.document_gif
        doc.action_update_access_rights(
            partners={self.doc_user_2.partner_id.id: ("edit", False)}
        )
        doc_as_user_2 = doc.with_user(self.doc_user_2)
        self.assertEqual(doc_as_user_2.user_permission, "edit")
        self.assertEqual(
            self.folder_b.with_user(self.doc_user_2).user_permission, "view"
        )
        self.assertFalse(doc_as_user_2.user_can_move)

        own_folder = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "audit3 user2 folder",
                "owner_id": self.doc_user_2.id,
            }
        )
        with self.assertRaises(AccessError):
            doc_as_user_2.write({"folder_id": own_folder.id})

        with self.assertRaises(AccessError):
            doc_as_user_2.write({"folder_id": False})
        with self.assertRaises(AccessError):
            doc_as_user_2.write({"user_folder_id": "MY"})
        self.assertEqual(doc.folder_id, self.folder_b)

    def test_f1_legitimate_root_moves_still_work(self):
        doc = self.env["documents.document"].create(
            {
                "type": "binary",
                "datas": TEXT,
                "name": "audit3 movable.txt",
                "folder_id": self.folder_b.id,
                "owner_id": self.doc_user.id,
            }
        )
        doc.with_user(self.doc_user).write({"user_folder_id": "MY"})
        self.assertFalse(doc.folder_id)
        self.assertEqual(doc.owner_id, self.doc_user)

        doc.with_user(self.document_manager).write({"user_folder_id": "COMPANY"})
        self.assertFalse(doc.folder_id)
        self.assertFalse(doc.owner_id)

    def test_f1_archive_escalation_via_root_move_is_closed(self):
        doc = self.document_gif
        doc.action_update_access_rights(
            partners={self.doc_user_2.partner_id.id: ("edit", False)}
        )
        doc_as_user_2 = doc.with_user(self.doc_user_2)
        with self.assertRaises(UserError):
            doc_as_user_2.action_archive()
        with self.assertRaises(AccessError):
            doc_as_user_2.write({"folder_id": False})
        self.assertEqual(doc.folder_id, self.folder_b)
        self.assertTrue(doc.active)
        with self.assertRaises(UserError):
            doc_as_user_2.action_archive()

    def test_f1_no_regression_on_foldered_documents(self):
        folder = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "audit3 editable folder",
                "owner_id": self.doc_user.id,
                "access_internal": "edit",
            }
        )
        doc = self.env["documents.document"].create(
            {
                "type": "binary",
                "datas": TEXT,
                "name": "audit3 in folder.txt",
                "folder_id": folder.id,
                "owner_id": self.doc_user.id,
            }
        )
        doc.with_user(self.doc_user_2).action_archive()
        self.assertFalse(doc.active)


@tagged("post_install", "-at_install")
class TestDocumentsArchiveAuthorization(TransactionCaseDocuments):
    def test_f7_archive_guard_is_su_aware(self):
        doc = self.env["documents.document"].create(
            {
                "type": "binary",
                "datas": TEXT,
                "name": "audit3 su archive.txt",
                "folder_id": False,
                "owner_id": self.doc_user.id,
            }
        )
        share_env_doc = doc.with_user(self.portal_user)
        self.assertTrue(share_env_doc.env.user.share)
        with self.assertRaises(UserError):
            share_env_doc.write({"active": False})
        share_env_doc.sudo().write({"active": False})
        self.assertFalse(doc.active)

    def test_f7_unlink_mixin_uses_action_archive(self):
        doc = self.env["documents.document"].create(
            {
                "type": "binary",
                "datas": TEXT,
                "name": "audit3 mixin doc.txt",
                "folder_id": self.folder_b.id,
                "owner_id": self.doc_user.id,
            }
        )
        messages_before = len(doc.message_ids)
        doc.write({"res_model": False, "res_id": False})
        doc.action_archive()
        self.assertFalse(doc.active)
        self.assertGreater(
            len(doc.message_ids),
            messages_before,
            "action_archive must log the trash message the mixin now relies on",
        )


@tagged("post_install", "-at_install")
class TestDocumentsFavorites(TransactionCaseDocuments):
    @users("documents@example.com")
    def test_toggle_user_favorite_requires_read_access(self):
        hidden = (
            self.env["documents.document"]
            .sudo()
            .create(
                {
                    "name": "hidden",
                    "type": "binary",
                    "owner_id": self.document_manager.id,
                    "access_internal": "none",
                    "access_via_link": "none",
                }
            )
        )
        document = self.env["documents.document"].browse(hidden.id)
        self.assertEqual(document.user_permission, "none")

        with self.assertRaises(AccessError):
            document.action_toggle_user_favorite()

        self.assertNotIn(self.env.user, hidden.favorite_user_ids)

    @users("documents@example.com")
    def test_toggle_user_favorite_still_works_for_a_viewer(self):
        shared = (
            self.env["documents.document"]
            .sudo()
            .create(
                {
                    "name": "shared",
                    "type": "binary",
                    "owner_id": self.document_manager.id,
                    "access_internal": "view",
                }
            )
        )
        document = self.env["documents.document"].browse(shared.id)
        self.assertEqual(document.user_permission, "view")

        document.action_toggle_user_favorite()
        self.assertTrue(document.is_user_favorite)
        self.assertIn(self.env.user, shared.favorite_user_ids)

        document.action_toggle_user_favorite()
        self.assertFalse(document.is_user_favorite)
        self.assertNotIn(self.env.user, shared.favorite_user_ids)


@tagged("post_install", "-at_install")
class TestDocumentsShareUserCreate(TransactionCaseDocuments):
    def test_s1a_share_user_cannot_create_root_document(self):
        Document = self.env["documents.document"].with_user(self.portal_user)
        with self.assertRaises(AccessError):
            Document.create(
                {
                    "name": "injected",
                    "type": "binary",
                    "folder_id": False,
                    "owner_id": False,
                    "company_id": False,
                    "access_internal": "edit",
                }
            )

    def test_s1a_share_user_create_does_not_elevate_access(self):
        folder = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "shared to portal",
                "access_via_link": "edit",
                "access_internal": "none",
            }
        )
        folder.action_update_access_rights(
            partners={self.portal_user.partner_id: ("edit", False)}
        )
        try:
            doc = (
                self.env["documents.document"]
                .with_user(self.portal_user)
                .create(
                    {
                        "name": "child",
                        "type": "url",
                        "url": "https://example.com",
                        "folder_id": folder.id,
                        "owner_id": False,
                        "access_internal": "edit",
                    }
                )
            )
        except AccessError:
            return
        self.assertNotEqual(doc.access_internal, "edit")


@tagged("post_install", "-at_install")
class TestDocumentsAccessRightsUpdate(TransactionCaseDocuments):
    def test_c5_member_kept_on_internal_downgrade(self):
        doc = (
            self.env["documents.document"]
            .with_user(self.document_manager)
            .create({"type": "binary", "name": "c5", "user_folder_id": "COMPANY"})
        )
        doc.with_user(self.document_manager).action_update_access_rights(
            access_internal="none",
            partners={self.internal_user.partner_id: ("view", False)},
        )
        member = doc.sudo().access_ids.filtered(
            lambda a: a.partner_id == self.internal_user.partner_id and a.role
        )
        self.assertTrue(member, "member grant must survive the internal downgrade")
        self.assertEqual(member.role, "view")

    def test_c5_sharing_wizard_no_crash_on_self_access_loss(self):
        if "documents.sharing" not in self.env:
            self.skipTest("documents_enterprise is not installed")
        doc = (
            self.env["documents.document"]
            .with_user(self.document_manager)
            .create({"type": "binary", "name": "c5w", "user_folder_id": "COMPANY"})
        )
        Sharing = self.env["documents.sharing"].with_user(self.document_manager)
        wizard = Sharing.browse(Sharing.action_open(doc.ids)["res_id"])
        wizard.write({"access_internal": "write_none"})
        result = wizard.action_update_rights()
        self.assertIsInstance(result, dict)


@tagged("post_install", "-at_install")
class TestDocumentsLock(TransactionCaseDocuments):
    def test_lock_enforced_server_side(self):
        other = self.env["res.users"].create(
            {
                "login": "doc_user_2",
                "name": "Doc User 2",
                "group_ids": [
                    Command.link(self.env.ref("documents.group_documents_user").id)
                ],
            }
        )
        doc = self.document_gif
        doc.action_update_access_rights(partners={other.partner_id.id: ("edit", False)})
        doc.with_user(self.doc_user).toggle_lock()
        self.assertEqual(doc.lock_uid, self.doc_user)

        with self.assertRaises(UserError):
            doc.with_user(other).write({"datas": TEXT})
        with self.assertRaises(UserError):
            doc.with_user(other).action_archive()

        doc.with_user(self.doc_user).write({"datas": TEXT})
        doc.with_user(self.document_manager).write({"datas": GIF})


@tagged("post_install", "-at_install")
class TestDocumentsAccessInheritance(TransactionCaseDocuments):
    def test_empty_access_ids_opts_out_of_inheritance(self):
        self.folder_a.action_update_access_rights(
            partners={self.portal_user.partner_id.id: ("view", False)}
        )
        opted_out = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "no-inherit",
                "folder_id": self.folder_a.id,
                "access_ids": [Command.set([])],
            }
        )
        self._assert_no_members(opted_out)
        self.assertFalse(opted_out.access_ids)

        inherited = self.env["documents.document"].create(
            {"type": "folder", "name": "inherit", "folder_id": self.folder_a.id}
        )
        self.assertIn(self.portal_user.partner_id, inherited.access_ids.partner_id)


@tagged("post_install", "-at_install")
class TestDocumentsLinkedRecordAuthorization(TransactionCaseDocuments):
    def test_request_wizard_requires_target_write_access(self):
        wizard_model = self.env["documents.request_wizard"]
        bad_model = wizard_model.with_user(self.doc_user).create(
            {
                "name": "req",
                "folder_id": self.folder_a.id,
                "requestee_id": self.doc_user.partner_id.id,
                "res_model": "no.such.model",
                "res_id": 1,
            }
        )
        with self.assertRaises(UserError):
            bad_model.request_document()

        param = (
            self.env["ir.config_parameter"]
            .sudo()
            .create({"key": "documents.review_fixes_probe", "value": "x"})
        )
        restricted = wizard_model.with_user(self.doc_user).create(
            {
                "name": "req",
                "folder_id": self.folder_a.id,
                "requestee_id": self.doc_user.partner_id.id,
                "res_model": "ir.config_parameter",
                "res_id": param.id,
            }
        )
        with self.assertRaises(AccessError):
            restricted.request_document()


@tagged("post_install", "-at_install")
class TestDocumentsOperationWizard(TransactionCaseDocuments):
    def test_operation_add_without_attachment_message(self):
        if "documents.operation" not in self.env:
            self.skipTest("documents_enterprise is not installed")
        wizard = self.env["documents.operation"].create(
            {"operation": "add", "destination": "MY"}
        )
        with self.assertRaises(UserError) as cm:
            wizard.action_confirm()
        self.assertEqual(str(cm.exception), "No attachment to add.")
