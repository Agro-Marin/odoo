"""Regression tests for the duplication removed from `documents.document`.

Each test pins an invariant that a *pair* of implementations used to encode
separately, so that collapsing them (or letting them drift again) fails loudly
rather than silently changing behaviour in one of the two.
"""

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests.common import tagged
from odoo.tools import mute_logger

from .test_documents_common import TransactionCaseDocuments


@tagged("post_install", "-at_install")
class TestDocumentsAttachmentVals(TransactionCaseDocuments):
    """`create()` and `write()` must agree on what belongs to the attachment."""

    def test_create_and_write_route_the_same_keys(self):
        """Every attachment-related key is batched onto the attachment, both ways.

        `write` used to hardcode datas/raw/mimetype while `create` derived the
        set from the field definitions, so description/attachment_name/
        attachment_type fell back to the per-record related write on one path
        only.
        """
        document = self.env["documents.document"].create(
            {
                "name": "vals.txt",
                "folder_id": self.folder_a.id,
                "raw": b"created",
                "mimetype": "text/plain",
                "description": "made-on-create",
            }
        )
        self.assertEqual(document.attachment_id.description, "made-on-create")
        self.assertEqual(document.attachment_id.raw, b"created")

        document.write({"description": "set-on-write", "raw": b"written"})
        document.invalidate_recordset()
        self.assertEqual(document.attachment_id.description, "set-on-write")
        self.assertEqual(document.attachment_id.raw, b"written")

    def test_unknown_field_reports_as_an_invalid_field(self):
        """An unknown key must reach the ORM, not die on a raw KeyError.

        `create` indexed `self._fields[key]` while scanning vals, so a typo in a
        create() call surfaced as `KeyError` — an HTTP 500 instead of a
        validation error.
        """
        with self.assertRaises(ValueError):
            self.env["documents.document"].create(
                {
                    "name": "typo",
                    "type": "binary",
                    "definitely_not_a_field": 1,
                }
            )

    @mute_logger("odoo.addons.base.models.ir_attachment")
    def test_derived_attachment_metadata_cannot_be_forged(self):
        """`checksum`/`index_content` always describe the stored bytes.

        They are `related="attachment_id.*"`, but `ir.attachment` strips them
        from its own vals, so a caller's value is discarded whichever route it
        takes. Pinned here because it is the reason `_pop_attachment_vals`
        deliberately does NOT carve them out: doing so would only move where
        they get dropped. Muted because the strip is reported now, and this is
        the caller it is meant to report.
        """
        document = self.env["documents.document"].create(
            {
                "name": "derived.txt",
                "folder_id": self.folder_a.id,
                "raw": b"real",
                "mimetype": "text/plain",
                "checksum": "forged",
                "index_content": "forged-index",
            }
        )
        document.invalidate_recordset()
        self.assertEqual(
            document.checksum,
            self.env["ir.attachment"]._content_checksum(b"real"),
            "checksum must describe the stored bytes, not what the caller sent",
        )
        self.assertNotEqual(document.index_content, "forged-index")


@tagged("post_install", "-at_install")
class TestDocumentsPropagationDomain(TransactionCaseDocuments):
    """Company propagation must not inherit access-only carve-outs."""

    def test_access_domain_layers_on_the_propagation_domain(self):
        """The access rule is the base rule plus whatever extensions narrow it.

        Asserting the two are *equal* would only hold with no extension
        installed -- `documents_spreadsheet` narrows the access one, and it
        auto-installs. What must hold either way is that the access domain is
        still built on the base one.
        """
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
        """`_update_company` must consult `_get_propagation_domain`, not the
        access one — otherwise an extension exempting a document from *sharing*
        changes silently also exempts it from *company* moves.
        """
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
class TestDocumentsShortcutFields(TransactionCaseDocuments):
    """A shortcut derives what it can; only the rest is copied from the target."""

    def test_copy_fields_hold_nothing_the_computes_already_resolve(self):
        copy_fields = self.env["documents.document"]._get_shortcuts_copy_fields()
        fields = self.env["documents.document"]._fields
        redundant = sorted(
            name
            for name in copy_fields
            if fields[name].compute and fields[name].readonly
        )
        self.assertFalse(
            redundant,
            "a readonly computed field cannot be seeded through create(): the "
            "value is discarded, so listing it here is dead code",
        )

    def test_shortcut_derives_its_own_name_size_and_extension(self):
        attachment = self.env["ir.attachment"].create(
            {
                "name": "target.txt",
                "raw": b"a" * 42,
                "mimetype": "text/plain",
            }
        )
        target = self.env["documents.document"].create(
            {
                "name": "target.txt",
                "folder_id": self.folder_a.id,
                "attachment_id": attachment.id,
            }
        )
        shortcut = target.action_create_shortcut(
            location_user_folder_id=str(self.folder_a.id)
        )
        shortcut.invalidate_recordset()

        self.assertEqual(shortcut.name, target.name)
        self.assertEqual(shortcut.file_size, target.file_size)
        self.assertEqual(shortcut.file_extension, target.file_extension)
        self.assertEqual(shortcut.type, target.type)

    def test_folder_shortcut_keeps_the_target_type(self):
        """`type` is readonly but NOT computed, so it does land — and it must:
        `_check_shortcut_fields` requires a shortcut to share its target's type.
        """
        target = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "folder target",
            }
        )
        shortcut = target.action_create_shortcut(
            location_user_folder_id=str(self.folder_a.id)
        )
        self.assertEqual(shortcut.type, "folder")


@tagged("post_install", "-at_install")
class TestDocumentsEmbeddedActions(TransactionCaseDocuments):
    """Pinning and listing must accept exactly the same server actions."""

    def _server_action(self, **extra):
        return self.env["ir.actions.server"].create(
            {
                "name": extra.pop("name", "dedup action"),
                "model_id": self.env["ir.model"]._get_id("documents.document"),
                "state": "code",
                "code": "pass",
                "usage": "ir_actions_server",
                **extra,
            }
        )

    def test_cannot_pin_an_action_the_listing_would_hide(self):
        """A child action is not embeddable, so pinning it must be refused.

        It used to be accepted: `action_folder_embed_action` filtered on the
        group domain alone while `_get_folder_embedded_actions` filtered on the
        stricter embeddable domain. The row it wrote was invisible for good, and
        clicking again stacked another one because the unpin lookup could not
        see it either.
        """
        parent = self._server_action(name="dedup parent")
        child = self._server_action(name="dedup child", parent_id=parent.id)
        folder = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "embed folder",
            }
        )

        with self.assertRaises(UserError):
            self.env["documents.document"].action_folder_embed_action(
                folder.id, child.id
            )
        self.assertFalse(
            self.env["ir.embedded.actions"].search_count(
                [
                    ("parent_res_id", "=", folder.id),
                    ("action_id", "=", child.id),
                ]
            ),
            "a refused pin must leave no orphan row behind",
        )

    def test_a_listable_action_still_pins_and_appears(self):
        action = self._server_action(name="dedup pinnable")
        folder = self.env["documents.document"].create(
            {
                "type": "folder",
                "name": "embed folder ok",
            }
        )
        self.env["documents.document"].action_folder_embed_action(folder.id, action.id)
        listed = self.env["documents.document"]._get_folder_embedded_actions(folder.ids)
        self.assertIn(
            action.id,
            listed.get(folder.id, self.env["ir.embedded.actions"]).action_id.ids,
        )


@tagged("post_install", "-at_install")
class TestDocumentsArchiveWording(TransactionCaseDocuments):
    """Both halves of the archive gate speak with one voice."""

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
        # The folder-permission half raises the shared wording verbatim.
        with self.assertRaises(UserError) as caught:
            document.with_user(self.internal_user)._raise_if_unauthorized_archive()
        self.assertEqual(str(caught.exception), message)


@tagged("post_install", "-at_install")
class TestDocumentsUserPermissionContract(TransactionCaseDocuments):
    """`user_permission` must stay READABLE, not just searchable.

    `_compute_user_permission` passes `company_domains` by keyword to
    `_search_user_permission`. An override stuck on the older signature raises
    TypeError on every read while `search()` — which calls positionally — keeps
    working, so the breakage hides until something renders a list or a kanban.
    That is exactly how it shipped broken in a downstream module.
    """

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
        """Both entry points hit the same domain, so they must not disagree."""
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
