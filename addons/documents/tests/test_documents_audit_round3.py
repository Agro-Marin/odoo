from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import tagged

from .test_documents_common import GIF, TEXT, TransactionCaseDocuments


@tagged("post_install", "-at_install")
class TestDocumentsAuditRound3(TransactionCaseDocuments):
    """Regression tests for the third-round audit fixes (F1-F9)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.doc_user_2 = cls.env["res.users"].create(
            {
                "login": "audit3_doc_user_2",
                "name": "Audit3 Doc User 2",
                "email": "audit3_doc_user_2@example.com",
                "group_ids": [
                    Command.link(cls.env.ref("documents.group_documents_user").id)
                ],
            }
        )

    # ------------------------------------------------------------------
    # F1 - `write({'folder_id': False})` skipped every move guard
    # ------------------------------------------------------------------

    def test_f1_move_to_root_is_guarded(self):
        """Moving out of a folder one cannot edit is refused, root included."""
        doc = self.document_gif  # in folder_b (owner: doc_user, internal: view)
        doc.action_update_access_rights(
            partners={self.doc_user_2.partner_id.id: ("edit", False)}
        )
        doc_as_user_2 = doc.with_user(self.doc_user_2)
        # Pre-condition: edit on the file, only view on the containing folder.
        self.assertEqual(doc_as_user_2.user_permission, "edit")
        self.assertEqual(
            self.folder_b.with_user(self.doc_user_2).user_permission, "view"
        )
        self.assertFalse(doc_as_user_2.user_can_move)

        # Control: moving into a folder of their own is already refused.
        own_folder = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "audit3 user2 folder",
                "owner_id": self.doc_user_2.id,
            }
        )
        with self.assertRaises(AccessError):
            doc_as_user_2.write({"folder_id": own_folder.id})

        # The bug: a move to the drive root took a completely unguarded path.
        with self.assertRaises(AccessError):
            doc_as_user_2.write({"folder_id": False})
        with self.assertRaises(AccessError):
            doc_as_user_2.write({"user_folder_id": "MY"})
        self.assertEqual(doc.folder_id, self.folder_b)

    def test_f1_legitimate_root_moves_still_work(self):
        """The owner may still move their own document to a drive root."""
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

        # A manager may move it to the Company root.
        doc.with_user(self.document_manager).write({"user_folder_id": "COMPANY"})
        self.assertFalse(doc.folder_id)
        self.assertFalse(doc.owner_id)

    def test_f1_archive_escalation_via_root_move_is_closed(self):
        """The full escalation chain: unauthorized move then trash.

        `_raise_if_unauthorized_archive` authorizes through the *containing
        folder*, so a document with no folder used to be trashable by anybody
        with edit on the file. The escalation is closed at the move: the
        document can no longer reach a root the user does not control.
        """
        doc = self.document_gif  # folder_b: owner doc_user, internal view
        doc.action_update_access_rights(
            partners={self.doc_user_2.partner_id.id: ("edit", False)}
        )
        doc_as_user_2 = doc.with_user(self.doc_user_2)
        # Step 1 (the guard that already worked): direct trash is refused.
        with self.assertRaises(UserError):
            doc_as_user_2.action_archive()
        # Step 2 (the hole): escaping to a root to lose the guard.
        with self.assertRaises(AccessError):
            doc_as_user_2.write({"folder_id": False})
        # Still in its folder, still protected.
        self.assertEqual(doc.folder_id, self.folder_b)
        self.assertTrue(doc.active)
        with self.assertRaises(UserError):
            doc_as_user_2.action_archive()

    def test_f1_no_regression_on_foldered_documents(self):
        """Archiving a document in a folder one can edit is still allowed."""
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

    # ------------------------------------------------------------------
    # F2 - shortcut access inherited from the folder instead of the target
    # ------------------------------------------------------------------

    def test_f2_shortcut_create_inherits_target_access(self):
        """A plain create() of a shortcut takes its access from the target."""
        target = self.env["documents.document"].create(
            {
                "type": "binary",
                "datas": GIF,
                "name": "audit3 private target",
                "folder_id": self.folder_a.id,
                "owner_id": self.doc_user.id,
                "access_via_link": "none",
                "access_internal": "none",
                "is_access_via_link_hidden": True,
            }
        )
        public_folder = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "audit3 public folder",
                "owner_id": self.doc_user.id,
                "access_via_link": "view",
                "access_internal": "view",
                "is_access_via_link_hidden": False,
            }
        )
        shortcut = self.env["documents.document"].create(
            {
                "shortcut_document_id": target.id,
                "folder_id": public_folder.id,
            }
        )
        # Must not have been published by the folder it was dropped into.
        self.assertEqual(shortcut.access_via_link, "none")
        self.assertEqual(shortcut.access_internal, "none")
        self.assertTrue(shortcut.is_access_via_link_hidden)

        # Explicit values still win over the target.
        explicit = self.env["documents.document"].create(
            {
                "shortcut_document_id": target.id,
                "folder_id": public_folder.id,
                "access_internal": "edit",
            }
        )
        self.assertEqual(explicit.access_internal, "edit")
        self.assertEqual(explicit.access_via_link, "none")

        # Non-shortcut documents keep inheriting from their folder.
        plain = self.env["documents.document"].create(
            {
                "type": "binary",
                "datas": TEXT,
                "name": "audit3 plain",
                "folder_id": public_folder.id,
            }
        )
        self.assertEqual(plain.access_via_link, "view")
        self.assertEqual(plain.access_internal, "view")

    # ------------------------------------------------------------------
    # F3 - action_create_shortcut skipped the check for the drive roots
    # ------------------------------------------------------------------

    def test_f3_shortcut_to_company_root_requires_manager(self):
        """A non-manager cannot inject a folder at the Company root."""
        folder = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "audit3 source folder",
                "owner_id": self.doc_user.id,
                "access_internal": "edit",
            }
        )
        with self.assertRaises(AccessError):
            folder.with_user(self.doc_user_2).action_create_shortcut("COMPANY")
        self.assertFalse(
            self.env["documents.document"].search_count(
                [
                    ("shortcut_document_id", "=", folder.id),
                    ("folder_id", "=", False),
                    ("owner_id", "=", False),
                ]
            )
        )

        # A manager may.
        shortcut = folder.with_user(self.document_manager).action_create_shortcut(
            "COMPANY"
        )
        self.assertTrue(shortcut._is_company_root_folder())

    def test_f3_shortcut_to_file_at_company_root_still_allowed(self):
        """Only the folder case is manager-only; files stay allowed."""
        doc = self.env["documents.document"].create(
            {
                "type": "binary",
                "datas": TEXT,
                "name": "audit3 shortcut file",
                "owner_id": self.doc_user_2.id,
            }
        )
        shortcut = doc.with_user(self.doc_user_2).action_create_shortcut("COMPANY")
        self.assertEqual(shortcut.shortcut_document_id, doc)
        self.assertFalse(shortcut._is_company_root_folder())

    def test_f3_shortcut_check_runs_before_sudo(self):
        """The check must happen before the internal sudo(), not inside create.

        `create`'s manager guard is intentionally sudo-bypassable (see
        `test_mail_gateway.test_alias_access`), so `action_create_shortcut`,
        which sudoes on the user's behalf, has to enforce it itself.
        """
        folder = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "audit3 sudo probe folder",
                "owner_id": self.doc_user.id,
                "access_internal": "edit",
            }
        )
        before = self.env["documents.document"].search_count(
            [("folder_id", "=", False), ("owner_id", "=", False)]
        )
        with self.assertRaises(AccessError):
            folder.with_user(self.doc_user_2).action_create_shortcut("COMPANY")
        self.assertEqual(
            self.env["documents.document"].search_count(
                [("folder_id", "=", False), ("owner_id", "=", False)]
            ),
            before,
            "a company root folder was created despite the refusal",
        )

    # ------------------------------------------------------------------
    # F4 - `_compute_res_name` was strictly linear
    # ------------------------------------------------------------------

    def test_f4_compute_res_name_is_batched(self):
        """res_name costs a constant number of queries per res_model."""
        partners = self.env["res.partner"].create(
            [{"name": f"audit3 partner {i}"} for i in range(20)]
        )
        documents = self.env["documents.document"].create(
            [
                {
                    "type": "binary",
                    "name": f"audit3 linked {i}",
                    "folder_id": self.folder_b.id,
                    "owner_id": self.doc_user.id,
                    "res_model": "res.partner",
                    "res_id": partner.id,
                }
                for i, partner in enumerate(partners)
            ]
        )
        self.assertFalse(documents.attachment_id)

        self.env.flush_all()
        documents.invalidate_recordset()
        self.env.invalidate_all()
        count0 = self.cr.sql_log_count
        names = documents.mapped("res_name")
        queries = self.cr.sql_log_count - count0

        self.assertEqual(names, partners.mapped("display_name"))
        # One query per document (the old behaviour) would be >= 20.
        self.assertLess(
            queries,
            len(documents),
            f"_compute_res_name still scales linearly ({queries} queries for "
            f"{len(documents)} documents)",
        )

    def test_f4_compute_res_name_fallbacks_preserved(self):
        """Deleted and unreadable linked records still degrade gracefully."""
        param = self.env["ir.config_parameter"].create(
            {"key": "documents.audit3_probe", "value": "x"}
        )
        ghost = self.env["res.partner"].create({"name": "audit3 ghost"})
        doc_restricted, doc_missing = self.env["documents.document"].create(
            [
                {
                    "type": "binary",
                    "name": "audit3 restricted link",
                    "folder_id": self.folder_b.id,
                    "owner_id": self.doc_user.id,
                    "res_model": "ir.config_parameter",
                    "res_id": param.id,
                },
                {
                    "type": "binary",
                    "name": "audit3 missing link",
                    "folder_id": self.folder_b.id,
                    "owner_id": self.doc_user.id,
                    "res_model": "res.partner",
                    "res_id": ghost.id,
                },
            ]
        )
        ghost.unlink()
        self.env.invalidate_all()

        self.assertEqual(doc_restricted.with_user(self.doc_user).res_name, "Restricted")
        self.assertFalse(doc_missing.res_name)

    def test_f4_compute_res_name_ignores_whether_an_attachment_exists(self):
        """res_name means the same thing with and without an attachment.

        Documents carrying an attachment used to delegate to
        `attachment_id.res_name`, which was wrong three ways:

        * it raised AccessError for a user holding document-level view but no
          direct access to the attachment -- a crash computing a field the
          kanban renders;
        * `ir.attachment._compute_res_name` degrades an inaccessible linked
          record to `False`, this model to "Restricted", so the value a user saw
          depended on whether the document happened to carry an attachment;
        * a plain upload resolved to its *own* name, since its attachment
          back-references the document (res_model='documents.document').
        """
        param = self.env["ir.config_parameter"].create(
            {"key": "documents.audit3_probe_attached", "value": "x"}
        )
        with_attachment, without_attachment = self.env["documents.document"].create(
            [
                {
                    "type": "binary",
                    "name": "audit3 attached restricted link",
                    "folder_id": self.folder_b.id,
                    "owner_id": self.doc_user.id,
                    "datas": TEXT,
                    "res_model": "ir.config_parameter",
                    "res_id": param.id,
                },
                {
                    "type": "binary",
                    "name": "audit3 bare restricted link",
                    "folder_id": self.folder_b.id,
                    "owner_id": self.doc_user.id,
                    "res_model": "ir.config_parameter",
                    "res_id": param.id,
                },
            ]
        )
        self.assertTrue(with_attachment.attachment_id)
        self.assertFalse(without_attachment.attachment_id)
        self.env.invalidate_all()

        # Same linked record, same verdict, attachment or not.
        self.assertEqual(
            with_attachment.with_user(self.doc_user).res_name, "Restricted"
        )
        self.assertEqual(
            without_attachment.with_user(self.doc_user).res_name, "Restricted"
        )

        # A plain upload links to nothing, so it names nothing -- it used to
        # report its own name through its attachment's back-reference.
        plain = self.env["documents.document"].create(
            {
                "type": "binary",
                "name": "audit3 plain upload",
                "folder_id": self.folder_b.id,
                "owner_id": self.doc_user.id,
                "datas": TEXT,
            }
        )
        self.assertTrue(plain.attachment_id)
        self.assertEqual(plain.attachment_id.res_model, "documents.document")
        self.assertFalse(plain.res_model)
        self.assertFalse(plain.res_name)

    def test_f4_compute_res_name_survives_an_uninstalled_model(self):
        """A stale res_model must degrade, not raise KeyError."""
        doc = self.env["documents.document"].create(
            {
                "type": "binary",
                "name": "audit3 stale model link",
                "folder_id": self.folder_b.id,
                "owner_id": self.doc_user.id,
            }
        )
        # res_model is a Char: it outlives the module that declared the model.
        doc.invalidate_recordset()
        self.env.cr.execute(
            "UPDATE documents_document SET res_model = %s, res_id = %s WHERE id = %s",
            ["gone.model", 1, doc.id],
        )
        doc.invalidate_recordset()
        self.assertFalse(doc.res_name)

    # ------------------------------------------------------------------
    # F5 - last_access_date_group dependencies
    # ------------------------------------------------------------------

    def test_f5_last_access_date_group_not_stale(self):
        """Changing last_access_date recomputes the bucket."""
        doc = self.document_gif
        access = doc.access_ids.filtered(
            lambda a: a.partner_id == self.doc_user.partner_id
        )
        self.assertTrue(access)
        access.last_access_date = fields.Datetime.now()
        self.assertEqual(doc.with_user(self.doc_user).last_access_date_group, "3_day")

        # Backdating must invalidate the computed bucket.
        access.last_access_date = fields.Datetime.subtract(
            fields.Datetime.now(), days=400
        )
        self.assertEqual(
            doc.with_user(self.doc_user).last_access_date_group,
            "0_older",
            "last_access_date_group did not follow last_access_date",
        )

    def test_f5_last_access_date_group_is_per_user(self):
        """One user reading the field must not poison another user's value."""
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

        # Whoever reads first used to fill a single shared cache entry.
        self.assertEqual(doc.with_user(self.doc_user).last_access_date_group, "3_day")
        self.assertEqual(
            doc.with_user(self.doc_user_2).last_access_date_group,
            "0_older",
            "last_access_date_group is shared between users (missing "
            "depends_context('uid'))",
        )

    # ------------------------------------------------------------------
    # F6 - tag uniqueness over a translated column
    # ------------------------------------------------------------------

    def test_f6_tag_name_unique_same_language(self):
        Tag = self.env["documents.tag"]
        Tag.create({"name": "Audit3DupTag"})
        with self.assertRaises(UserError):
            Tag.create({"name": "Audit3DupTag"})
        with self.assertRaises(UserError):
            Tag.create([{"name": "Audit3Batch"}, {"name": "Audit3Batch"}])

    def test_f6_tag_name_unique_across_translations(self):
        """A translated name must not let a duplicate through."""
        self.env["res.lang"]._activate_lang("fr_FR")
        Tag = self.env["documents.tag"]
        tag = Tag.create({"name": "Audit3TransTag"})
        tag.with_context(lang="fr_FR").name = "Audit3TransTagFR"
        # The jsonb documents now differ, but the English name still collides.
        with self.assertRaises(UserError):
            Tag.create({"name": "Audit3TransTag"})
        self.assertEqual(
            Tag.search([("name", "=", "Audit3TransTag")]),
            tag,
        )

    # ------------------------------------------------------------------
    # F7 - unlink mixin / sudo consistency
    # ------------------------------------------------------------------

    def test_f7_archive_guard_is_su_aware(self):
        """sudo() bypasses the share-user archive guard like every other one."""
        doc = self.env["documents.document"].create(
            {
                "type": "binary",
                "datas": TEXT,
                "name": "audit3 su archive.txt",
                # No folder: keeps the trash-chatter branch (which posts as a
                # non-su portal user and cannot create a mail.message) out of
                # the way, so this test isolates the share guard itself.
                "folder_id": False,
                "owner_id": self.doc_user.id,
            }
        )
        share_env_doc = doc.with_user(self.portal_user)
        self.assertTrue(share_env_doc.env.user.share)
        # Without sudo, a share user is still refused.
        with self.assertRaises(UserError):
            share_env_doc.write({"active": False})
        # With sudo, the internal code path goes through, like the other guards.
        share_env_doc.sudo().write({"active": False})
        self.assertFalse(doc.active)

    def test_f7_unlink_mixin_uses_action_archive(self):
        """The mixin's archive path produces the trash chatter.

        No model inheriting ``documents.unlink.mixin`` is installed by the
        ``documents`` module alone, so this asserts the observable effect the
        mixin now relies on: ``action_archive`` logs the trash message that a
        raw ``write({'active': False})`` never produced.
        """
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

    # ------------------------------------------------------------------
    # F9 - small fixes
    # ------------------------------------------------------------------

    def test_f9_user_folder_id_accepts_int(self):
        """An RPC caller passing an int folder id gets a move, not a traceback."""
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
        """kwargs reach super() for fields other than user_folder_id."""
        result = self.env["documents.document"].search_panel_select_range(
            "folder_id", enable_counters=True
        )
        self.assertIn("values", result)

    def test_f9_search_filter_names_are_unique(self):
        """The two root filters no longer share a name."""
        view = self.env.ref("documents.document_view_search")
        arch = view.arch_db
        self.assertIn('name="my_drive_filter"', arch)
        self.assertIn('name="in_company_filter"', arch)
        self.assertEqual(arch.count('name="my_drive_filter"'), 1)
