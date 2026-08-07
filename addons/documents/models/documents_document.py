import base64
import contextlib
import io
import logging
import re
import string
import uuid
from collections import defaultdict
from typing import Any
from urllib.parse import quote
from urllib.parse import urlencode as url_encode

import requests
from dateutil.relativedelta import relativedelta

import odoo
from odoo import SUPERUSER_ID, Command, _, api, fields, models, modules
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.fields import Domain
from odoo.libs.filesystem import get_extension
from odoo.tools import groupby
from odoo.tools.image import image_process
from odoo.tools.misc import clean_context
from odoo.tools.pdf import PdfFileReader

from odoo.addons.documents.tools import UserFolder
from odoo.addons.mail.tools import link_preview

_logger = logging.getLogger(__name__)


def _sanitize_file_extension(extension: str) -> str:
    """Remove leading and trailing spacing and any leading dot from an extension."""
    return re.sub(r"^[\s.]+|\s+$", "", extension)


class DocumentsDocument(models.Model):
    """Store documents, folders and shortcuts with their access rights."""

    _name = "documents.document"
    _description = "Document"
    _inherit = ["mail.thread.cc", "mail.activity.mixin", "mail.alias.mixin.optional"]
    _mail_post_access = "read"
    _order = "sequence, id desc"
    _parent_name = "folder_id"
    _parent_store = True
    _systray_view = "activity"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        index=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Contact",
        tracking=True,
        index="btree_not_null",
    )
    owner_id = fields.Many2one(
        "res.users",
        string="Owner",
        default=lambda self: self.env.user.id if self.env.user.active else False,
        copy=False,
        index=True,
        tracking=True,
    )
    # Attachment
    attachment_id = fields.Many2one(
        "ir.attachment",
        ondelete="cascade",
        bypass_search_access=True,
        copy=False,
    )
    attachment_name = fields.Char(
        "Attachment Name",
        related="attachment_id.name",
        readonly=False,
    )
    description = fields.Text(
        "Attachment Description",
        related="attachment_id.description",
        readonly=False,
    )
    attachment_type = fields.Selection(
        string="Attachment Type",
        related="attachment_id.type",
        readonly=False,
    )
    checksum = fields.Char(
        related="attachment_id.checksum",
    )
    mimetype = fields.Char(
        related="attachment_id.mimetype",
    )
    index_content = fields.Text(
        related="attachment_id.index_content",
    )
    raw = fields.Binary(
        related="attachment_id.raw",
        related_sudo=True,
        readonly=False,
        prefetch=False,
    )
    datas = fields.Binary(
        related="attachment_id.datas",
        related_sudo=True,
        readonly=False,
        prefetch=False,
    )

    shortcut_document_id = fields.Many2one(
        "documents.document",
        "Source Document",
        ondelete="cascade",
        index="btree_not_null",
    )
    shortcut_document_owner_id = fields.Many2one(
        "res.users",
        "Source Document Owner",
        related="shortcut_document_id.owner_id",
        store=True,
    )
    shortcut_ids = fields.One2many("documents.document", "shortcut_document_id")

    file_size = fields.Integer(
        compute="_compute_file_size",
        store=True,
    )
    res_model = fields.Char(
        "Resource Model",
        compute="_compute_res_record",
        store=True,
        inverse="_inverse_res_record",
        recursive=True,
    )
    res_model_name = fields.Char(
        compute="_compute_res_model_name",
    )
    res_id = fields.Many2oneReference(
        "Resource ID",
        model_field="res_model",
        compute="_compute_res_record",
        store=True,
        inverse="_inverse_res_record",
        recursive=True,
    )
    res_name = fields.Char(
        "Resource Name",
        compute="_compute_res_name",
    )

    # Versioning
    previous_attachment_ids = fields.Many2many(
        "ir.attachment",
        string="History",
        bypass_search_access=True,
    )

    # Document
    name = fields.Char(
        "Name",
        copy=True,
        compute="_compute_name_and_preview",
        store=True,
        readonly=False,
        recursive=True,
        translate=True,
        tracking=True,
    )
    active = fields.Boolean(default=True, string="Active")
    sequence = fields.Integer("Sequence", default=10)
    type = fields.Selection(
        [("url", "URL"), ("binary", "File"), ("folder", "Folder")],
        default="binary",
        string="Type",
        required=True,
        readonly=True,
        index=True,
    )
    thumbnail = fields.Binary(
        attachment=True,
        compute="_compute_thumbnail",
        store=True,
        recursive=True,
        readonly=False,
    )
    thumbnail_status = fields.Selection(
        [
            ("present", "Present"),  # Document has a thumbnail
            ("error", "Error"),  # Error when generating the thumbnail
            (
                "client_generated",
                "Client Generated",
            ),  # The PDF thumbnail is generated by the user browser
        ],
        compute="_compute_thumbnail",
        store=True,
        recursive=True,
        readonly=False,
    )
    url = fields.Char(
        "Link URL",
        size=1024,
        index=True,
        tracking=True,
    )
    url_preview_image = fields.Char(
        "URL Preview Image",
        compute="_compute_name_and_preview",
        store=True,
        readonly=False,
        recursive=True,
    )
    url_preview_pending = fields.Boolean(
        "URL preview to fetch",
        default=False,
        copy=False,
        help="Set when a URL document still needs its link preview fetched "
        "asynchronously (see _cron_update_url_preview).",
    )
    request_activity_id = fields.Many2one("mail.activity")
    requestee_partner_id = fields.Many2one("res.partner")
    tag_ids = fields.Many2many("documents.tag", "document_tag_rel", string="Tags")
    lock_uid = fields.Many2one("res.users", string="Locked by", tracking=True)
    favorited_ids = fields.Many2many("res.users", string="Favorite of")
    is_favorited = fields.Boolean(
        compute="_compute_is_favorited",
        inverse="_inverse_is_favorited",
    )

    # Access
    document_token = fields.Char(
        required=True,
        default=lambda __: (
            base64.urlsafe_b64encode(uuid.uuid4().bytes).decode().removesuffix("==")
        ),
        copy=False,
        # No `index=`: the `_document_token_unique` constraint below already
        # creates a unique b-tree index, which serves token lookups; a second
        # index would just be extra write overhead.
    )
    access_token = fields.Char(compute="_compute_access_token")

    access_url = fields.Char(string="Access url", compute="_compute_access_url")
    is_access_via_link_hidden = fields.Boolean(
        "Link Access Hidden",
        index=True,
        help='If "True", only people given direct access to this document will be able to view it. '
        'If "False", access with the link also given to all who can access the parent folder.',
    )
    access_via_link = fields.Selection(
        [("view", "Viewer"), ("edit", "Editor"), ("none", "None")],
        string="Link Access Rights",
        required=True,
        default="none",
        index=True,
    )
    is_download_blocked = fields.Boolean(
        "Block Download",
        default=False,
        help="If set, people who can only view this document cannot download "
        "it. Editors are unaffected: they can replace the content, so "
        "withholding it from them would mean nothing.",
    )
    access_internal = fields.Selection(
        [("view", "Viewer"), ("edit", "Editor"), ("none", "None")],
        string="Internal Users Rights",
        required=True,
        default="none",
        index=True,
    )

    access_ids = fields.One2many(
        "documents.access",
        "document_id",
        string="Allowed Access",
    )

    user_permission = fields.Selection(
        [("edit", "Editor"), ("view", "Viewer"), ("none", "None")],
        string="User permission",
        compute="_compute_user_permission",
        compute_sudo=True,
        search="_search_user_permission",
    )
    user_can_move = fields.Boolean(
        string="Can move it",
        compute="_compute_user_can_move",
    )

    # Folder = parent document
    parent_path = fields.Char(
        index=True
    )  # see '_parent_store' implementation in the ORM for details
    folder_id = fields.Many2one(
        "documents.document",
        string="Folder",
        required=False,
        ondelete="set null",
        domain="[('type', '=', 'folder'), ('shortcut_document_id', '=', False)]",
        index=True,
        search="_search_folder_id",
        tracking=True,
    )
    user_folder_id = fields.Char(
        string="Parent",
        compute="_compute_user_folder_id",
        search="_search_user_folder_id",
    )
    children_ids = fields.One2many("documents.document", "folder_id")

    deletion_delay = fields.Integer(
        "Deletion delay",
        compute="_compute_deletion_delay",
        help="Delay after permanent deletion of the document in the trash (days)",
    )

    # Activity
    create_activity_option = fields.Boolean(
        string="Create a new activity",
        compute="_compute_create_activity_option",
        store=True,
        readonly=False,
    )
    create_activity_type_id = fields.Many2one(
        "mail.activity.type",
        string="Activity type",
    )
    create_activity_summary = fields.Char("Summary")
    create_activity_date_deadline_range = fields.Integer(string="Due Date In")
    create_activity_date_deadline_range_type = fields.Selection(
        [
            ("days", "Days"),
            ("weeks", "Weeks"),
            ("months", "Months"),
        ],
        string="Due type",
        default="days",
    )
    create_activity_note = fields.Html(string="Note")
    create_activity_user_id = fields.Many2one(
        "res.users",
        string="Responsible",
    )

    # Actions that we can do on the document
    available_embedded_actions_ids = fields.Many2many(
        "ir.embedded.actions",
        string="Available Actions",
        compute="_compute_available_embedded_actions_ids",
        groups="base.group_user",
    )

    # Alias
    alias_tag_ids = fields.Many2many(
        "documents.tag",
        "document_alias_tag_rel",
        string="Alias Tags",
    )
    mail_alias_domain_count = fields.Integer(
        "Mail Alias Domain Count",
        compute="_compute_mail_alias_domain_count",
    )

    is_editable_attachment = fields.Boolean(
        default=False,
        help="True if we can edit the link attachment.",
    )
    is_multipage = fields.Boolean(
        "Is considered multipage",
        compute="_compute_is_multipage",
        store=True,
        readonly=False,
    )
    file_extension = fields.Char(
        "File Extension",
        compute="_compute_file_extension",
        inverse="_inverse_file_extension",
        store=True,
        readonly=False,
        copy=True,
    )

    # UI fields
    last_access_date_group = fields.Selection(
        selection=[
            ("0_older", "Older"),
            ("1_month", "This Month"),
            ("2_week", "This Week"),
            ("3_day", "Today"),
        ],
        string="Last Accessed On",
        compute="_compute_last_access_date_group",
        search="_search_last_access_date_group",
    )

    _res_model_res_id_idx = models.Index("(res_model, res_id)")

    # ------------------------------------------------------------
    # CONSTRAINTS
    # ------------------------------------------------------------

    _attachment_unique = models.Constraint(
        "unique (attachment_id)",
        "This attachment is already a document",
    )
    _document_token_unique = models.Constraint(
        "unique (document_token)",
        "Access tokens already used.",
    )
    _folder_id_not_id = models.Constraint(
        "check(folder_id <> id)",
        "A folder cannot be included in itself",
    )
    _shortcut_document_id_not_id = models.Constraint(
        "check(shortcut_document_id <> id)",
        "A shortcut cannot point to itself",
    )

    @api.constrains("document_token")
    def _check_document_token(self) -> None:
        charset = set(string.ascii_letters + string.digits + "-_")
        for document in self:
            if (
                len(document.document_token or "") != 22
                or set(document.document_token) - charset
            ):
                raise ValidationError(_("Invalid document token"))

    @api.constrains(
        "shortcut_document_id",
        "shortcut_ids",
        "type",
        "folder_id",
        "children_ids",
        "company_id",
    )
    def _check_shortcut_fields(self) -> None:
        errors = []
        wrong_types, wrong_companies = self.browse(), self.browse()
        chained_shortcuts = self.browse()
        # Access rights can allow for a document to be edited without having access to its parent folder
        wrong_parents_sudo = self.folder_id.sudo().filtered("shortcut_document_id")
        for target in self.filtered("shortcut_ids"):
            for shortcut in target.shortcut_ids:
                if shortcut.type != target.type:
                    wrong_types |= shortcut
        for shortcut in self.filtered("shortcut_document_id"):
            if shortcut.type != shortcut.shortcut_document_id.type:
                wrong_types |= shortcut
            if shortcut.children_ids:
                wrong_parents_sudo |= shortcut
            # Every consumer resolves exactly one hop, and
            # `action_create_shortcut` already normalizes a shortcut target back
            # to the real document. `create` accepted a chain anyway, and the
            # result is silent data loss: the outer shortcut shows no name and no
            # extension, and deleting the *middle* shortcut cascade-deletes it
            # (ondelete='cascade') even though the real document is untouched.
            if shortcut.shortcut_document_id.sudo().shortcut_document_id:
                chained_shortcuts |= shortcut
            if (
                shortcut.shortcut_document_id.company_id
                and shortcut.shortcut_document_id.company_id != shortcut.company_id
            ):
                wrong_companies |= shortcut
        if wrong_types:
            message = _("The following documents/shortcuts have a type mismatch: \n")
            documents_list = "\n- ".join(wrong_types.mapped("name"))
            errors.append(f"{message}\n- {documents_list}")
        if wrong_parents_sudo:
            message = _(
                "The following shortcuts cannot be set as documents parents: \n"
            )
            shortcuts_list = "\n- ".join(wrong_parents_sudo.mapped("name"))
            errors.append(f"{message}\n- {shortcuts_list}")
        if wrong_companies:
            message = _("The following documents/shortcuts have a company mismatch: \n")
            shortcuts_list = "\n- ".join(wrong_companies.mapped("name"))
            errors.append(f"{message}\n- {shortcuts_list}")
        if chained_shortcuts:
            message = _(
                "The following shortcuts point at another shortcut instead of a "
                "document: \n"
            )
            shortcuts_list = "\n- ".join(chained_shortcuts.mapped("name"))
            errors.append(f"{message}\n- {shortcuts_list}")
        if errors:
            raise ValidationError("\n\n".join(errors))

    @api.constrains("owner_id", "folder_id")
    def _check_root_documents_owner_id(self) -> None:
        root_documents = self.filtered(lambda d: not d.folder_id)
        unauthorized_owners_sudo = (
            root_documents._get_unauthorized_root_document_owners_sudo()
        )
        if unauthorized_owners_sudo:
            users_documents_list = [
                (document.owner_id.name, document.name)
                for document in root_documents
                if document.owner_id in unauthorized_owners_sudo
            ]
            raise ValidationError(
                _(
                    "The following user(s) cannot own root documents/folders: \n- %(lines)s",
                    lines="\n-".join(
                        f"{user_name}: {doc_name}"
                        for user_name, doc_name in users_documents_list
                    ),
                )
            )

    @api.constrains("res_model")
    def _check_res_model(self) -> None:
        if self.filtered(lambda d: d.res_model == "documents.document"):
            raise ValidationError(
                _("A document can not be linked to itself or another document.")
            )

    @api.constrains("url")
    def _check_url(self) -> None:
        for document in self.filtered("url"):
            if not document.url.startswith(("https://", "http://", "ftp://")):
                raise ValidationError(
                    _(
                        "URL %s does not seem complete, as it does not begin with http(s):// or ftp://",
                        document.url,
                    )
                )

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    def _pop_attachment_vals(self, vals: dict) -> dict:
        """Split the attachment-bound keys out of *vals*, mutating it in place.

        ``raw``/``datas``/``mimetype``/``description``/... are all
        ``related="attachment_id.*"``. Written through the related field they go
        one record at a time, and ``mimetype`` cannot go through at all (it is
        readonly on ``ir.attachment``), so both :meth:`create` and :meth:`write`
        hand them to the attachment in a single batched write instead.

        The two used to disagree about which keys those are: ``create`` derived
        the set from the field definitions while ``write`` hardcoded three of
        them, so ``attachment_name``/``attachment_type``/``description`` were
        batched on create and fell back to the per-record related write on
        write -- the exact cost the split exists to avoid.

        Derived metadata (``checksum``, ``index_content``) is deliberately NOT
        special-cased: ``ir.attachment._normalize_content_vals`` strips those
        from its own vals, so a caller's value is discarded whichever way it
        travels. Carving them out here would only move where that happens.

        :return: the values to write on the attachment
        """
        keys = [
            key
            for key in list(vals)
            # `.get`, not `[]`: an unknown key must travel on to the ORM, which
            # reports it as an invalid field. Indexing `_fields` here turned a
            # typo in a create() call into a bare KeyError (an HTTP 500).
            if (field := self._fields.get(key)) is not None
            and field.related
            and field.related.split(".")[0] == "attachment_id"
        ]
        return {key: vals.pop(key) for key in keys}

    @api.model_create_multi
    def create(self, vals_list: list[dict]) -> DocumentsDocument:
        """Create documents, inheriting access rights from the containing folder.

        Access rights fields (access_ids, access_internal, access_via_link) are
        inherited from the containing folder unless specified in vals or context
        defaults.
        """
        attachments = []
        for vals in vals_list:
            attachment_dict = self._pop_attachment_vals(vals)
            attachment = self.env["ir.attachment"].browse(vals.get("attachment_id"))
            self._clean_vals_for_user_folder_id(vals, is_create=True)
            self._check_parent_folder_in_vals(vals)
            # Share (portal/public) users may only create documents *inside* a
            # folder they can reach, and may never elevate internal/link access.
            # Their legitimate creation flows all go through sudo controllers, so
            # a non-sudo share create at the root (folder_id=False) with e.g.
            # access_internal='edit' is an injection into the shared Company space
            # (readable/editable by every internal user) -- reject it.
            if not self.env.su and self.env.user.share:
                if not vals.get("folder_id"):
                    raise AccessError(
                        _("You are not allowed to create documents here.")
                    )
                for access_field in ("access_internal", "access_via_link"):
                    vals.pop(access_field, None)
            if attachment and attachment_dict:
                attachment.write(attachment_dict)
            elif attachment_dict:
                attachment_dict.setdefault("name", vals.get("name", "unnamed"))
                # default_res_model and default_res_id will cause unique constraints to trigger.
                attachment = (
                    self.env["ir.attachment"]
                    .with_context(clean_context(self.env.context))
                    .create(attachment_dict)
                )
                vals["attachment_id"] = attachment.id
                vals["name"] = vals.get("name", attachment.name)
            if attachment and not vals.get("name"):
                # Seed the name at INSERT time. `name` is a *stored computed*
                # field with `tracking=True`: letting `_compute_name_and_preview`
                # fill it in after the row exists registers as a tracked change,
                # so every upload posted a spurious empty-bodied tracking message
                # (body='', tracking on `name`) into the chatter.
                vals["name"] = attachment.name
            attachments.append(attachment)

        # don't allow using default_access_ids
        documents = super(
            DocumentsDocument, self.with_context(default_access_ids=None)
        ).create(vals_list)

        # NOTE: `_is_documents_manager()` is true under `sudo()`, so it skips the
        # two guards below. That is an explicit contract here
        # (`test_mail_gateway.test_alias_access` asserts a plain user may set an
        # alias through `sudo()`), so callers that sudo *on behalf of a user*
        # must check first -- see `action_create_shortcut`.
        if not self._is_documents_manager():
            if any(d.alias_name for d in documents):
                raise AccessError(_("Only Documents Managers can set aliases."))
            if any(d._is_company_root_folder() for d in documents):
                self._raise_company_folder_manager_only()

        for document, attachment in zip(documents, attachments, strict=True):
            if (
                attachment
                and not attachment.res_id
                and (
                    not attachment.res_model
                    or attachment.res_model == "documents.document"
                )
            ):
                attachment.with_context(no_document=True).write(
                    {
                        "res_model": "documents.document",
                        "res_id": document.id,
                    }
                )
        self._mark_url_preview_pending(documents)
        return documents

    @api.model
    def _shortcut_access_defaults(self, target: DocumentsDocument) -> dict:
        """Return the access a shortcut takes from its *target*.

        A shortcut exposes its target, not whatever sits in the folder it was
        dropped into, so both creation paths (`action_create_shortcut` and a
        plain `create()` going through `_prepare_create_values`) must derive
        these from the target and agree on the fallbacks.
        """
        return {
            "access_internal": target.access_internal or "view",
            "access_via_link": target.access_via_link or "none",
        }

    @api.model
    def _trigger_url_preview_cron(self) -> None:
        """Wake the link-preview cron, if it still exists.

        Both the producer (a url document was written) and the cron itself
        (a full batch means more are pending) need this, and neither may assume
        the cron record survived an uninstall.
        """
        cron = self.env.ref("documents.ir_cron_url_preview", raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    def _locked_by_other(self) -> DocumentsDocument:
        """Return the documents locked by *another* user.

        A lock stops a second editor replacing content or trashing the file. The
        exemptions (superuser, managers) are the part that must not drift
        between the two guards, so they live here; the two call sites keep their
        own message because "cannot be replaced" and "cannot be trashed" are
        different things to tell a user.
        """
        if self.env.su or self._is_documents_manager():
            return self.browse()
        return self.filtered(lambda d: d.lock_uid and d.lock_uid != self.env.user)

    @api.model
    def _check_parent_folder_in_vals(self, vals: dict) -> None:
        """Refuse a ``folder_id`` in ``vals`` that is not a folder.

        ``write`` rejects this with "Invalid folder id"; ``create`` accepted it,
        producing a child hanging off a *binary* document. Such a child is
        invisible in the folder tree (which filters ``type='folder'``) yet is
        still archived and deleted along with the file it hangs off: orphaned,
        unreachable data.

        A shortcut-to-folder parent is deliberately *not* resolved here. The
        create/write difference for shortcuts is intentional and asserted
        together in `test_shortcuts_cant_have_children`: create refuses it
        (through `_check_shortcut_fields`, which a shortcut reaches because it
        shares its target's ``type``), while a move resolves it to the target.
        """
        if not vals.get("folder_id"):
            return
        # sudo: access rights can allow filing into a folder the user cannot
        # read, the same reason `_check_shortcut_fields` reads parents in sudo.
        if self.browse(vals["folder_id"]).sudo().type != "folder":
            raise UserError(_("Invalid folder id"))

    def write(self, vals: dict) -> bool:
        """Write values on the documents, handling moves, versioning and access."""
        if "shortcut_document_id" in vals:
            raise UserError(_("Shortcuts cannot change target document."))

        # `action_archive` owns the archive transition: the lock guard, the
        # `_raise_if_unauthorized_archive` / `_raise_if_used_folder` checks, the
        # child cascade and the trash log all live there. A raw
        # `write({"active": False})` used to be a second, unguarded door to the
        # same state change -- reachable over plain RPC and used by
        # `/documents/pdf_split` -- so it could trash a locked document, a folder
        # another app is wired to, or a document the user may not archive.
        # Delegate instead of duplicating the guards, the way
        # `documents.unlink.mixin` already does. The context flag marks the write
        # issued by `action_archive` itself, which must not re-enter here.
        #
        # `sudo()` keeps the previous direct path, consistent with every other
        # privilege guard in this method (locked content, owner change, folder
        # move) -- `action_archive` re-checks `unlink` access as a *non-su* user
        # (it calls `.sudo(False)`), so routing sudo writes through it would make
        # sudo stricter than a plain write rather than a bypass.
        if (
            vals.get("active") is False
            and not self.env.su
            and not self.env.context.get("documents_archiving")
        ):
            if remaining_vals := {k: v for k, v in vals.items() if k != "active"}:
                self.write(remaining_vals)
            self.action_archive()
            return True

        self._clean_vals_for_user_folder_id(vals)

        is_manager = self._is_documents_manager()
        pinned_folders_start = self.filtered(lambda d: d._is_company_root_folder())

        # A locked document may only have its content replaced by the user who
        # locked it (or a manager). The web client enforces this, but so must the
        # server, otherwise a second editor or a raw RPC write bypasses the lock.
        # (Archiving is enforced separately in `action_archive`, scoped to the
        # directly-targeted records so folder cascades are not blocked by a locked
        # child.)
        # `raw` and `datas` are two `related="attachment_id.*"` aliases for the
        # same bytes, and both are writable. Everything below used to key on the
        # literal `"datas"`, so a `raw` write took the lock guard (which does
        # test both) but silently skipped versioning, the request-fulfilment
        # chatter and the attachment auto-creation: replacing content through
        # `raw` destroyed the previous version, and writing it to a document
        # with no attachment yet was a *no-op that lost the upload*. Resolve the
        # content key once here and let the rest of the method reason about
        # "content", not about a field name.
        # The guard tests KEY PRESENCE, not truthiness. Keying it on a truthy
        # value asked "is new content arriving?" where the rule is "is the
        # current content being changed?", and the two differ exactly where it
        # matters: `{"raw": b""}`, `{"raw": False}`, `{"datas": b""}` and
        # `{"datas": False}` all walked past the lock and emptied the file, and
        # `{"attachment_id": False}` detached it outright -- that one without
        # even leaving a version behind, since the versioning branch below is
        # also skipped, so the web client's history offered no way back.
        # Emptying a file IS replacing its content.
        content_keys = ("datas", "raw")
        writes_content = any(key in vals for key in content_keys)
        has_content = any(vals.get(key) for key in content_keys)
        replaces_content = writes_content or "attachment_id" in vals
        if replaces_content and (locked_by_other := self._locked_by_other()):
            raise UserError(
                _(
                    "“%(name)s” is locked by %(user)s and its content cannot "
                    "be replaced by another user.",
                    name=locked_by_other[0].name,
                    user=locked_by_other[0].lock_uid.name,
                )
            )

        previous_owner_access_to_keep = {}
        documents_per_initial_active = {}

        if (owner_id := vals.get("owner_id")) is not None:
            if not is_manager and any(d.owner_id != self.env.user for d in self):
                raise AccessError(
                    _("You cannot change the owner of documents you do not own.")
                )
            if not isinstance(owner_id, int | bool | None):
                owner_id = owner_id.id
            documents_changing_owner = self.filtered(
                lambda d: d.owner_id and d.owner_id.id != owner_id
            )
            previous_owner_access_to_keep.update(
                documents_changing_owner.grouped("owner_id")
            )

        new_parent_folder = self.browse()
        documents_to_move, documents_to_move_per_initial_folder = (
            self.browse(),
            self.browse(),
        )

        # `folder_id` may legitimately be written as ``False`` (move to a drive
        # root, e.g. through `user_folder_id` = "MY"/"COMPANY"). Testing for
        # truthiness skipped this whole block for those moves, letting a user
        # move documents they are not allowed to move out of a folder they
        # cannot edit -- and, downstream, archive/delete them once they no
        # longer had a parent folder to authorize against.
        if "folder_id" in vals:
            self._check_parent_folder_in_vals(vals)
            new_parent_folder = self.browse(vals["folder_id"])
            documents_to_move = self.filtered(
                lambda d: d.folder_id != new_parent_folder
            )
            if documents_to_move and new_parent_folder and not new_parent_folder.active:
                raise UserError(
                    _("It is not possible to move documents into archived folders.")
                )
            if documents_to_move and not self.env.su:
                if new_parent_folder and new_parent_folder.user_permission != "edit":
                    raise AccessError(_("You can't access that folder_id."))
                for doc in documents_to_move:
                    if doc.user_permission != "edit":
                        raise AccessError(
                            _("You are not allowed to move (some of) these documents.")
                        )
                    if not doc.user_can_move:
                        raise AccessError(
                            _(
                                "You can't move documents you do not own out of folders you cannot edit."
                            )
                        )

            if new_parent_folder.shortcut_document_id:
                # `user_folder_id` is dropped, not carried: the first pass has
                # already merged everything it derives into `vals`, and it still
                # names the *shortcut*. Re-entering with both made
                # `_clean_vals_for_user_folder_id` compare the shortcut it
                # re-derives against the resolved target and refuse the move with
                # "Conflicting values passed with user_folder_id" -- so dropping
                # a document onto a shortcut-folder failed through
                # `user_folder_id` (what the web client sends) while the same
                # move through `folder_id` worked.
                resolved_vals = vals | {
                    "folder_id": new_parent_folder.shortcut_document_id.id
                }
                resolved_vals.pop("user_folder_id", None)
                return self.write(resolved_vals)

            # Only for a move *into a folder*: detaching an archived document to
            # a drive root has always been allowed and is relied upon (see
            # `test_documents_document.test_unarchive_document_with_archived_parent`).
            if new_parent_folder:
                for doc in documents_to_move:
                    to_active = vals.get("active")
                    if (not doc.active and not to_active) or (
                        doc.folder_id
                        and not doc.folder_id.active
                        and (not to_active or doc.folder_id not in self)
                    ):
                        raise UserError(
                            _("It is not possible to move archived documents.")
                        )
            documents_to_move_per_initial_folder = documents_to_move.grouped(
                "folder_id"
            )

        if (to_active := vals.get("active")) is not None:
            if to_active is False:
                # Consistent with the other privilege guards in this method
                # (locked content, owner change, folder move): sudo bypasses.
                if not self.env.su and self.env.user.share:
                    raise UserError(_("You are not allowed to (un)archive documents."))
                self.check_access(
                    "unlink"
                )  # As archived gc leads to unlink after `deletion_delay` days.
            documents_per_initial_active = self.grouped("active")

        attachment_id = vals.get("attachment_id")
        if attachment_id:
            self.ensure_one()

        attachments_was_present = []
        versioned = self.browse()  # documents that gained a history entry below
        for record in self:
            attachments_was_present.append(bool(record.attachment_id))
            if (
                record.type == "binary"
                and (writes_content or "url" in vals)
                # `datas`/`raw` are prefetch=False related fields, so testing
                # them would read (and, for `datas`, base64-encode) the entire
                # old file just to check for emptiness. The stored attachment
                # metadata answers the same
                # question ("was the document empty, i.e. a pending request?")
                # without materializing the payload.
                and (not record.attachment_id or not record.attachment_id.file_size)
            ):
                body = _(
                    "Document Request: %(name)s Uploaded by: %(user)s",
                    name=record.name,
                    user=self.env.user.name,
                )
                record.with_context(no_document=True).message_post(body=body)

            if record.attachment_id:
                # versioning
                if attachment_id and attachment_id != record.attachment_id.id:
                    # Link the new attachment to the related record and link the previous one
                    # to the document.
                    attachment = self.env["ir.attachment"].browse(attachment_id)
                    if (attachment.res_model, attachment.res_id) != (
                        record.res_model,
                        record.res_id,
                    ):
                        attachment.with_context(no_document=True).write(
                            {
                                "res_model": record.res_model or "documents.document",
                                "res_id": record.res_id
                                if record.res_model
                                else record.id,
                            }
                        )

                    related_record = record.res_model and self.env[
                        record.res_model
                    ].browse(record.res_id)
                    if (
                        not hasattr(related_record, "message_main_attachment_id")
                        or related_record.message_main_attachment_id
                        != record.attachment_id
                    ):
                        record.attachment_id.with_context(no_document=True).write(
                            {"res_model": "documents.document", "res_id": record.id}
                        )
                    if attachment_id in record.previous_attachment_ids.ids:
                        record.previous_attachment_ids = [(3, attachment_id, False)]
                    record.previous_attachment_ids = [
                        (4, record.attachment_id.id, False)
                    ]
                    versioned |= record
                elif writes_content:
                    # ``elif``: when a new ``attachment_id`` is also supplied the
                    # branch above already archived the previous attachment; the
                    # incoming content lands on the new attachment, so copying
                    # the old one again here would double-version it.
                    old_attachment = record.attachment_id.with_context(
                        no_document=True
                    ).copy()
                    # removes the link between the old attachment and the record.
                    old_attachment.write(
                        {
                            "res_model": "documents.document",
                            "res_id": record.id,
                        }
                    )
                    record.previous_attachment_ids = [(4, old_attachment.id, False)]
                    versioned |= record
            elif has_content and not vals.get("attachment_id"):
                res_model = vals.get("res_model", record.res_model)
                res_id = vals.get("res_id", record.res_id)
                if res_model and not self.env[res_model].browse(res_id).exists():
                    record.res_model = False
                    record.res_id = False

                attachment = (
                    self.env["ir.attachment"]
                    .with_context(no_document=True)
                    .create(
                        {
                            "name": vals.get("name", record.name),
                            "res_model": record.res_model or "documents.document",
                            "res_id": record.res_id if record.res_model else record.id,
                        }
                    )
                )
                record.attachment_id = attachment.id

        # Pop every attachment-bound key so they are written in one batch on the
        # ir.attachment (same rule as create(); see _pop_attachment_vals).
        attachment_dict = self._pop_attachment_vals(vals)

        if not is_manager and set(vals) & set(self.env["mail.alias.mixin"]._fields):
            raise AccessError(_("Only Documents Managers can set aliases."))

        write_result = super().write(vals)
        if attachment_dict:
            self.attachment_id.write(attachment_dict)

        if "attachment_id" in vals:
            self.attachment_id.check_access("read")

        # After the write, so the version just added is counted against the cap.
        versioned._prune_versions()

        if (new_active := vals.get("active")) is not None:
            if not new_active:
                if self.sudo().search(
                    [("id", "child_of", self.ids), ("active", "=", True)]
                ):
                    raise UserError(
                        _(
                            'Operation not supported. Please use "Move to Trash" / `action_archive` instead.'
                        )
                    )
                if archived_documents := documents_per_initial_active.get(
                    True
                ):  # Log moved to trash instead of "archived"
                    archived_documents._log_transition_to_parent_folders(
                        lambda names: self.env._(
                            "The following documents have been sent to trash: "
                            "%(documents)s.",
                            documents=names,
                        )
                    )
            elif new_active:
                if self.sudo().search(
                    [("id", "parent_of", self.ids), ("active", "=", False)]
                ):
                    raise UserError(
                        _(
                            'Operation not supported. Please use "Restore" / `action_unarchive` instead.'
                        )
                    )
                if restored_documents := documents_per_initial_active.get(
                    False
                ):  # Log restored instead of "unarchived"
                    restored_documents._log_transition_to_parent_folders(
                        lambda names: self.env._(
                            "The following documents have been restored from the "
                            "trash: %(documents)s.",
                            documents=names,
                        )
                    )

        if (
            not is_manager
            and self.filtered(lambda d: d._is_company_root_folder())
            != pinned_folders_start
        ):
            self._raise_company_folder_manager_only()

        for document, attachment_was_present in zip(
            self, attachments_was_present, strict=True
        ):
            if (
                document.request_activity_id
                and document.attachment_id
                and not attachment_was_present
            ):
                feedback = _(
                    "Document Request: %(name)s Uploaded by: %(user)s",
                    name=document.name,
                    user=self.env.user.name,
                )
                document.with_context(
                    no_document=True
                ).request_activity_id.action_feedback(
                    feedback=feedback, attachment_ids=[document.attachment_id.id]
                )

        if (
            (company_id := vals.get("company_id")) is not None
        ) and self.shortcut_ids | self.children_ids:
            self._update_company(company_id)

        # Ensure edit role for previous owners
        self._ensure_user_role_without_propagation(
            "edit", previous_owner_access_to_keep
        )

        if new_parent_folder and (
            documents_to_sync := documents_to_move.filtered(
                lambda d: not d.shortcut_document_id
            )
        ):
            documents_to_sync.action_update_access_rights(
                access_internal=new_parent_folder.access_internal,
                access_via_link=new_parent_folder.access_via_link,
                # Simply add partners of destination
                partners={
                    access.partner_id: (access.role, access.expiration_date)
                    for access in new_parent_folder.access_ids
                    if access.role
                },
            )
            # Propagate folder company unless passed as well (already done)
            if "company_id" not in vals:
                documents_to_sync._update_company(new_parent_folder.company_id.id)

        if documents_to_move:
            # A move to a drive root has no destination folder to log into, but
            # the folder the documents left must still record the move.
            for folder, documents in documents_to_move.grouped("folder_id").items():
                if folder:
                    folder.message_post_with_source(
                        source_ref="documents.folder_notification_move_in",
                        render_values={"documents": documents},
                    )
            for folder, documents in documents_to_move_per_initial_folder.items():
                if folder:
                    folder.message_post_with_source(
                        source_ref="documents.folder_notification_move_out",
                        render_values={"documents": documents},
                    )

        if "url" in vals:
            self._mark_url_preview_pending(self)

        return write_result

    def copy(self, default: dict | None = None) -> DocumentsDocument:
        """Duplicate the documents in ``self`` handling folders, shortcuts and access."""
        if not self:
            return self
        if not all(self.mapped("active")):
            raise UserError(_("You cannot duplicate document(s) in the Trash."))
        if default and default.get("user_folder_id") == UserFolder.MY:
            default["owner_id"] = self.env.user.id

        # As we avoid to propagate the folder permission by setting access_ids to False (see copy_data), user has no
        # right to create the document. So after checking permission, we execute the copy in sudo.
        self.env["documents.document"].check_access("create")
        self.check_access("read")
        documents_order = {doc.id: idx for idx, doc in enumerate(self)}
        new_documents = [self.browse()] * len(self)
        is_manager = self._is_documents_manager()
        skip_documents = self.env.context.get("documents_copy_folders_only")

        shortcuts = self.filtered("shortcut_document_id")
        if shortcuts and not skip_documents:
            for destination, targets in self._get_copy_shortcuts_destinations(
                shortcuts, default
            ):
                new_shortcuts = targets.action_create_shortcut(
                    location_user_folder_id=destination
                )
                for new_shortcut, target in zip(new_shortcuts, targets, strict=True):
                    new_shortcut.name = _("%s (copy)", target.name)
                    new_documents[documents_order[target.id]] = new_shortcut

        folders = (self - shortcuts).filtered(lambda d: d.type == "folder")
        if folders:
            if (
                not is_manager
                and default
                and default.get("user_folder_id") == UserFolder.COMPANY
            ):
                self._raise_company_folder_manager_only()

            embedded_actions = self._get_folder_embedded_actions(folders.ids)
            new_folders = folders.sudo()._copy_with_access(default=default).sudo(False)

            # move in "My Drive" if needed
            self.browse(
                [
                    new_folder.id
                    for old_folder, new_folder in zip(folders, new_folders, strict=True)
                    if old_folder._cannot_create_sibling()
                ]
            ).sudo().write({"folder_id": False})

            for old_folder, new_folder in zip(folders, new_folders, strict=True):
                if folder_embedded_actions := embedded_actions.get(old_folder.id):
                    embedded_actions_copies = folder_embedded_actions.copy()
                    embedded_actions_copies.parent_res_id = new_folder.id
                # no need to check for permission as all the checks have been done
                children_default = {"folder_id": new_folder.id}
                owner_id_in_default = (default or {}).get("owner_id") is not None
                if owner_id_in_default:
                    children_default.update(owner_id=default["owner_id"])

                # check if we are not copying a folder into itself or one of its descendants
                if new_folder.parent_path.startswith(old_folder.parent_path):
                    raise UserError(
                        _(
                            "You cannot copy a folder into itself or into one of its own descendants."
                        )
                    )
                old_folder.children_ids.with_context(
                    documents_copy_skip_rename=True
                ).copy(children_default)

                new_documents[documents_order[old_folder.id]] = new_folder
                if (
                    is_manager
                    and old_folder._is_company_root_folder()
                    and not owner_id_in_default
                ):
                    new_folder.owner_id = old_folder.owner_id

        if not skip_documents and (
            documents_sudo := (self - shortcuts - folders).sudo()
        ):
            new_binaries_sudo = documents_sudo._copy_with_access(default=default)
            for old_document_sudo, new_binary_sudo in zip(
                documents_sudo, new_binaries_sudo, strict=True
            ):
                new_documents[documents_order[old_document_sudo.id]] = (
                    new_binary_sudo.sudo(False)
                )
                if (
                    is_manager
                    and "owner_id" not in (default or {})
                    and (
                        not old_document_sudo.owner_id
                        and not old_document_sudo.folder_id
                    )  # company root
                ):
                    new_binary_sudo.owner_id = False
            # move in "My Drive" if needed
            self.browse(
                [
                    new_binary_sudo.id
                    for new_binary_sudo in new_binaries_sudo
                    if new_binary_sudo.sudo(self.env.su)._cannot_create_sibling()
                ]
            ).sudo().write({"folder_id": False})

            if to_copy_attachment_sudo := documents_sudo._copy_attachment_filter(
                default
            ):
                new_attachments_iterator = iter(
                    to_copy_attachment_sudo.attachment_id.with_context(
                        no_document=True
                    ).copy()
                )
                # Avoid recompute based on attachment_id
                with self.env.protecting(
                    self._get_fields_to_recompute(depends=["attachment_id"]),
                    new_binaries_sudo,
                ):
                    for old_document_sudo, new_binary_sudo in zip(
                        documents_sudo, new_binaries_sudo, strict=True
                    ):
                        if old_document_sudo in to_copy_attachment_sudo:
                            new_attachment = next(new_attachments_iterator)
                            new_binary_sudo.write(
                                {
                                    "attachment_id": new_attachment.id,
                                    "res_id": False,
                                    "res_model": False,
                                }
                            )

        # Skip the slots nothing was copied into. `new_documents` is pre-filled
        # with empty recordsets so results can be placed by input position, and
        # `documents_copy_folders_only` deliberately leaves the non-folder slots
        # untouched -- whose `.id` is `False`. Browsing those produced a
        # malformed recordset (`len()` counted them, `.ids` did not) that blew up
        # on the first field read.
        return self.browse(
            [new_document.id for new_document in new_documents if new_document]
        )

    def copy_data(self, default: dict | None = None) -> list[dict]:
        """Return the list of values used to duplicate the documents in ``self``."""
        default = dict(default or {})
        if "user_folder_id" in default:
            self._clean_vals_for_user_folder_id(default)
        vals_list = super().copy_data(default=default)
        if "name" not in default:
            for document, vals in zip(self, vals_list, strict=True):
                vals["name"] = (
                    document.name
                    if self.env.context.get("documents_copy_skip_rename")
                    else _("%s (copy)", document.name)
                )
        for vals in vals_list:
            # Avoid to propagate folder access as we want to copy the document accesses alone
            vals["access_ids"] = default.get("access_ids", False)
            if "owner_id" not in vals:
                vals["owner_id"] = self.env.user.id
        return vals_list

    def copy_translations(self, new, excluded=()):
        # ``copy_data`` renames ``name`` in the duplicating user's language
        # only; without this the copy would keep the source record's exact
        # ``name`` in every other language.
        super().copy_translations(new, excluded=(*excluded, "name"))
        self._copy_translations_of_renamed_field(
            new, "name", lambda record, term: record.env._("%s (copy)", term)
        )

    def unlink(self) -> bool:
        """Clean unused linked records too.

        This applies to:
          * Children documents when deleting the parent folder
          * Parent folder if it is archived and has no other children and user is allowed to
          * Attachment if document-related record is deleted
        """
        to_delete = self._with_descendants_sudo().sudo(False)
        removable_parent_folders = self._get_removable_parent_folders()
        # `to_delete`, not `self`: the cascade below deletes the whole subtree, so
        # scoping this to the directly-targeted records orphaned every
        # descendant's externally-pointed attachment (filestore blob + row) that
        # a direct delete would have reclaimed.
        removable_attachments = to_delete.attachment_id.filtered(
            lambda a: a.res_model != "documents.document"
        )

        res = super(DocumentsDocument, to_delete).unlink()

        if removable_attachments:
            removable_attachments.unlink()
        if removable_parent_folders:
            with contextlib.suppress(AccessError):
                removable_parent_folders.unlink()
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_unauthorized(self) -> None:
        try:
            self.check_access("unlink")
        except UserError as e:  # Hide potentially unknown inaccessible content's name.
            raise UserError(_("You are not allowed to delete all these items.")) from e
        self._raise_if_unauthorized_archive()

    @api.ondelete(at_uninstall=False)
    def _unlink_except_company_folders(self) -> None:
        self._raise_if_used_folder()

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    @api.depends("document_token")
    def _compute_access_token(self) -> None:
        for document in self:
            document.access_token = f"{document.document_token}o{document.id or 0:x}"

    @api.depends("access_token")
    def _compute_access_url(self) -> None:
        for document in self:
            document.access_url = f"{document.sudo().get_base_url()}/odoo/documents/{quote(document.access_token, safe='')}"

    @api.depends("create_activity_type_id", "create_activity_user_id")
    def _compute_create_activity_option(self) -> None:
        to_activate = self.filtered(
            lambda d: d.create_activity_type_id and d.create_activity_user_id
        )
        to_activate.create_activity_option = True
        (self - to_activate).create_activity_option = False

    @api.depends("folder_id", "company_id")
    @api.depends_context("uid", "allowed_company_ids", "documents_show_parent_name")
    def _compute_display_name(self) -> None:
        accessible_records = self._filtered_access("read")
        not_accessible_records = self - accessible_records
        not_accessible_records.display_name = _("Restricted")
        folders = accessible_records.filtered(lambda d: d.type == "folder")
        for record in folders:
            if record.user_permission != "none":
                record.display_name = (
                    record.name
                    if not self.env.context.get("documents_show_parent_name")
                    or not record.folder_id
                    else _(
                        "%(record)s (in %(parent)s)",
                        record=record.name,
                        parent=record.folder_id.name,
                    )
                )
            else:
                record.display_name = _("Restricted Folder")

        for record in accessible_records - folders:
            record.display_name = record.name

    @api.depends("name", "type", "shortcut_document_id.name")
    def _compute_file_extension(self) -> None:
        for record in self:
            if record.type != "binary":
                record.file_extension = False
            elif record.shortcut_document_id.name:
                file_extension = _sanitize_file_extension(
                    get_extension(record.shortcut_document_id.name.strip())
                )
                record.file_extension = file_extension or False
            elif record.name:
                record.file_extension = (
                    _sanitize_file_extension(get_extension(record.name.strip()))
                    or False
                )

    @api.depends(
        "attachment_id.file_size", "shortcut_document_id.attachment_id.file_size"
    )
    def _compute_file_size(self) -> None:
        shortcuts = self.filtered("shortcut_document_id")
        for document in self - shortcuts:
            document.file_size = document.attachment_id.file_size
        for document in shortcuts:
            document.file_size = document.shortcut_document_id.file_size

    @api.depends(
        "attachment_id",
        "url",
        "shortcut_document_id",
        "shortcut_document_id.name",
        "shortcut_document_id.url_preview_image",
    )
    def _compute_name_and_preview(self) -> None:
        shortcuts = self.filtered("shortcut_document_id")
        for record in self - shortcuts:
            if record.attachment_id:
                record.name = record.attachment_id.name
                record.url_preview_image = False
            elif record.url and not record.name:
                # Provide a name synchronously. The rich preview (og:title and
                # og:image) requires an outbound HTTP request, which must NOT run
                # inside this write transaction (it would hold row locks and a
                # worker on external latency); it is fetched later by
                # `_cron_update_url_preview`, flagged via `url_preview_pending`.
                record.name = record.url

        for shortcut in shortcuts:
            shortcut.name = shortcut.name or shortcut.shortcut_document_id.name
            shortcut.url_preview_image = (
                shortcut.url_preview_image
                or shortcut.shortcut_document_id.url_preview_image
            )

    def _mark_url_preview_pending(self, documents: DocumentsDocument) -> None:
        """Flag URL documents for asynchronous link-preview fetching."""
        to_fetch = documents.filtered(
            lambda d: d.type == "url" and d.url and not d.shortcut_document_id
        )
        if not to_fetch:
            return
        to_fetch.url_preview_pending = True
        self._trigger_url_preview_cron()

    @api.model
    def _cron_update_url_preview(self, limit: int = 200) -> None:
        """Fetch og:title/og:image for pending URL documents, off any request.

        Runs outside the user write transaction so external latency never holds
        row locks or a worker. Each document is committed on its own so one slow
        or failing host does not roll back the others. The name is only replaced
        while it still holds the placeholder (the raw URL), never an explicit
        user rename.
        """
        documents = self.search(
            [("url_preview_pending", "=", True), ("type", "=", "url")], limit=limit
        )
        if not documents:
            return
        session = requests.Session()
        for document in documents:
            vals = {"url_preview_pending": False}
            # get_link_preview_from_url returns None on any failure (bad host,
            # SSRF-blocked target, timeout) rather than raising, so a single bad
            # URL clears its flag without disturbing the rest of the batch.
            preview = (
                link_preview.get_link_preview_from_url(document.url, session)
                if document.url
                else None
            )
            if preview:
                if preview.get("og_title") and document.name in (False, document.url):
                    vals["name"] = preview["og_title"]
                if preview.get("og_image"):
                    vals["url_preview_image"] = preview["og_image"]
            document.write(vals)
            # Commit each document independently so a later slow/failing host (or
            # a run killed by ``limit_time_real``) cannot roll back the previews
            # already fetched, which would otherwise livelock on the slow hosts.
            # Committing is forbidden inside a test transaction, so skip it there.
            if not modules.module.current_test:
                self.env.cr.commit()

        if len(documents) == limit:
            # The batch was full: more documents may still be pending. Re-trigger
            # instead of waiting for the next scheduled interval (up to a day).
            self._trigger_url_preview_cron()

    @api.depends("checksum", "mimetype")
    def _compute_is_multipage(self) -> None:
        for document in self:
            # external computation to be extended
            document.is_multipage = bool(document._get_is_multipage())  # None => False

    @api.depends(
        "attachment_id",
        "attachment_id.res_model",
        "attachment_id.res_id",
        "shortcut_document_id.res_model",
        "shortcut_document_id.res_id",
    )
    def _compute_res_record(self) -> None:
        for record in self:
            attachment = record.attachment_id
            if attachment:
                record.res_model = (
                    attachment.res_model != "documents.document"
                    and attachment.res_model
                ) or False
                record.res_id = (
                    attachment.res_model != "documents.document" and attachment.res_id
                ) or False
            if record.shortcut_document_id:
                record.res_model = record.shortcut_document_id.res_model
                record.res_id = record.shortcut_document_id.res_id

    @api.depends("res_model", "res_id")
    def _compute_res_name(self) -> None:
        # Resolve from THIS model's res_model/res_id for every document, with or
        # without an attachment. Documents carrying one used to delegate to
        # `attachment_id.res_name`, which made the same field mean two different
        # things: `ir.attachment._compute_res_name` degrades an inaccessible
        # linked record to `False`, this one to "Restricted", so which of the two
        # a user saw depended on whether the document happened to have an
        # attachment. The delegation also pointed a plain upload at itself (its
        # attachment carries res_model='documents.document', res_id=<this
        # document>), so res_name was the document's own name -- dead data, since
        # both display sites gate on res_model, which `_compute_res_record`
        # leaves False for exactly those rows.
        linked = self.filtered(lambda d: d.res_id and d.res_model)
        # Browsing one id at a time gives every related record a prefetch set of
        # one, i.e. one query per document. Warm `display_name` in batches of one
        # query per `res_model` instead; the per-record fallback below still
        # handles deleted/unreadable records individually.
        for res_model, documents in linked.grouped("res_model").items():
            if res_model not in self.env:
                continue
            with contextlib.suppress(MissingError, AccessError):
                self.env[res_model].browse(documents.mapped("res_id")).exists().mapped(
                    "display_name"
                )

        (self - linked).res_name = False
        for record in linked:
            if record.res_model not in self.env:
                # model gone (module uninstalled) -- degrade like a missing record
                record.res_name = False
                continue
            try:
                record.res_name = (
                    self.env[record.res_model].browse(record.res_id).display_name
                )
            except MissingError:
                record.res_name = False
            except AccessError:
                # The document is readable but the linked record is not:
                # do not leak its name (the compute is no longer sudo).
                record.res_name = _("Restricted")

    @api.depends(
        "checksum",
        "mimetype",
        "shortcut_document_id.thumbnail",
        "shortcut_document_id.thumbnail_status",
    )
    def _compute_thumbnail(self) -> None:
        for document in self:
            if document.shortcut_document_id:
                document.thumbnail = document.shortcut_document_id.thumbnail
                document.thumbnail_status = (
                    document.shortcut_document_id.thumbnail_status
                )
            elif document.mimetype and (
                document.mimetype.startswith("application/pdf")
                or document.mimetype.startswith("image/webp")
            ):
                # These thumbnails are generated by the client. To force the generation, we invalidate the thumbnail.
                document.thumbnail = False
                document.thumbnail_status = "client_generated"
            elif document.mimetype and document.mimetype.startswith("image/"):
                # `_read_prefix`, not `raw`: this compute also assigns
                # `thumbnail_status`, a Selection, so `Binary.compute_value` does
                # not clear `bin_size` for it -- and `web_save` reads back under
                # `bin_size=True` unconditionally. `raw` therefore handed
                # `image_process` a size string (`b"129.00 bytes"`) on every
                # content replacement made through the web client, and the
                # failure was STORED: `thumbnail_status='error'` over a
                # thumbnail that had just been dropped. `sudo()` keeps the
                # elevation `raw`'s `related_sudo=True` provided.
                content = document.attachment_id.sudo()._read_prefix()
                try:
                    thumbnail = (
                        image_process(content, size=(200, 140), crop="center")
                        if content
                        else None
                    )
                except UserError, TypeError:
                    thumbnail = None
                document.thumbnail = base64.b64encode(thumbnail) if thumbnail else False
                document.thumbnail_status = "present" if thumbnail else "error"
            else:
                document.thumbnail = False
                document.thumbnail_status = False

    @api.depends("type")
    def _compute_deletion_delay(self) -> None:
        folders = self.filtered(lambda d: d.type == "folder")
        folders.deletion_delay = self.get_deletion_delay()
        (self - folders).deletion_delay = False

    @api.depends("favorited_ids")
    # `allowed_company_ids`: `_filtered_access` evaluates record rules, which are
    # company-scoped.
    @api.depends_context("uid", "allowed_company_ids")
    def _compute_is_favorited(self) -> None:
        favorited = self._filtered_access("read").filtered(
            lambda d: self.env.user in d.favorited_ids
        )
        favorited.is_favorited = True
        (self - favorited).is_favorited = False

    @api.depends("res_model")
    def _compute_res_model_name(self) -> None:
        for record in self:
            if record.res_model:
                record.res_model_name = (
                    self.env["ir.model"]._get(record.res_model).display_name
                )
            else:
                record.res_model_name = False

    # ------------------------------------------------------------
    # INVERSE METHODS
    # ------------------------------------------------------------

    def _inverse_file_extension(self) -> None:
        for record in self:
            file_extension = (
                _sanitize_file_extension(record.file_extension)
                if record.file_extension
                else False
            )
            (record | record.shortcut_ids).file_extension = file_extension

    def _inverse_res_record(self) -> None:
        # Group attachments by their target (res_model, res_id) so mass-linking a
        # selection to the same record issues one write per target instead of one
        # per document.
        attachments_by_target = defaultdict(lambda: self.env["ir.attachment"])
        # Targets the document points at *itself*: reaching the document already
        # gates them, so they are exempt from the write check below.
        self_link_targets = set()
        for record in self:
            attachment = record.attachment_id

            # If no linked record, link the attachment to the document
            # (so users see the attachment in the technical view if they have access to the document)
            res_model, res_id = record.res_model, record.res_id
            if not res_model:
                res_model = "documents.document"
                res_id = record.id
                self_link_targets.add((res_model, res_id))

            if attachment and (attachment.res_model, attachment.res_id) != (
                res_model,
                res_id,
            ):
                attachments_by_target[(res_model, res_id)] |= attachment

        for (res_model, res_id), attachments in attachments_by_target.items():
            # Rebinding an attachment to a record is an `ir.attachment` ACL
            # decision, but the write below has to be `sudo()` (see the atomicity
            # note). Without this guard that sudo also swallows
            # `ir.attachment.check()`, so any Documents user could plant a file on
            # the chatter of *any* record of *any* model -- including models they
            # cannot even read -- by setting `res_model`/`res_id` on a document.
            # This is the same target check `documents.link_to_record_wizard` and
            # `documents.request_wizard` already perform; enforcing it here covers
            # the plain `create()`/`write()` paths they were bypassing.
            if (
                not self.env.su
                and (res_model, res_id) not in self_link_targets
                and res_model in self.env
            ):
                self.env[res_model].browse(res_id).check_access("write")
            # Avoid inconsistency in the data, write both at the same time.
            # In case a check_access is done between res_id and res_model modification,
            # an access error can be received. (Mail causes this check_access)
            #
            # `no_document` belongs on *this* write, not on the attachments
            # gathered above: recordset union keeps the left operand's
            # environment (core says so in as many words -- "returning arg would
            # leak arg's env"), and the accumulator above starts as a plain
            # `self.env["ir.attachment"]`. Setting the context on the right-hand
            # value therefore dropped it before it could ever reach a write.
            #
            # Without it, linking a document to a record whose model inherits
            # `documents.mixin` (hr.employee, project.project, product.template,
            # account.move, ...) re-enters `ir.attachment.write` ->
            # `_create_document`, which creates a *second* document for the same
            # attachment: a duplicate where nothing stops it, and a
            # `documents_document_attachment_unique` violation -- an HTTP 422 out
            # of the upload route -- where the constraint does.
            attachments.sudo().with_context(no_document=True).write(
                {"res_model": res_model, "res_id": res_id}
            )

    def _inverse_is_favorited(self) -> None:
        # Set (not toggle) semantics: honour the written ``is_favorited`` value
        # rather than flipping the current membership, so an explicit
        # ``write({"is_favorited": True/False})`` (or a stale client toggle) is
        # idempotent instead of inverting.
        unfavorited_documents = favorited_documents = self.env[
            "documents.document"
        ].sudo()
        for document in self:
            if document.is_favorited:
                favorited_documents |= document
            else:
                unfavorited_documents |= document
        favorited_documents.write({"favorited_ids": [(4, self.env.uid)]})
        unfavorited_documents.write({"favorited_ids": [(3, self.env.uid)]})

    # ------------------------------------------------------------
    # SEARCH METHODS
    # ------------------------------------------------------------

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

    def action_move_folder(
        self, target: str, before_folder_id: int | bool = False
    ) -> bool | None:
        """Move one folder to the given position and update its sequence.

        If no parent_folder is given, check whether the parent is 'COMPANY' or
        'MY'. If no before_folder is given, place it as last child of its parent
        (last root if no parent is given).

        :param str target: user_folder_id of the new parent folder
        :param int|bool before_folder_id: id of the folder before which to move
        """
        self.ensure_one()
        if self.type != "folder" or not self.active:
            return None

        values = {"user_folder_id": target}
        sibling_folders_domain = (
            Domain("type", "=", "folder")
            & Domain("id", "!=", self.id)
            & Domain("user_folder_id", "=", target)
        )

        # If before_folder is indeed a sibling given the passed target (as it could have been moved by someone else),
        # assign its current sequence value to the current record and shift the following folders to keep ordering.
        # `.exists()` guards against a sibling deleted by a concurrent session
        # (browse() is truthy for any non-zero id), which would otherwise raise
        # MissingError when reading `.sequence`.
        if before_folder := self.browse(before_folder_id).exists():
            located_after_domain = Domain("sequence", ">", before_folder.sequence) | (
                Domain("sequence", "=", before_folder.sequence)
                & Domain("id", "<=", before_folder_id)
            )
            folders_to_resequence_domain = sibling_folders_domain & located_after_domain
            folders_to_resequence_sudo = self.sudo().search(
                folders_to_resequence_domain
            )
            # before_folder may no longer match the sibling domain (moved to
            # another parent concurrently), leaving the search empty; fall through
            # to the "last child" branch instead of indexing [0].
            if (
                folders_to_resequence_sudo
                and before_folder == folders_to_resequence_sudo[0]
            ):
                values["sequence"] = before_folder.sequence
                new_sequence = before_folder.sequence + 1
                for folder_sudo in folders_to_resequence_sudo:
                    if folder_sudo.sequence >= new_sequence:
                        break
                    folder_sudo.sequence = new_sequence
                    new_sequence += 1
                return self.write(values)

        # Otherwise, move the folder as last child of its parent
        if (
            result := self.env["documents.document"]
            .sudo()
            .search_read(
                sibling_folders_domain,
                fields=["sequence"],
                order="sequence DESC",
                limit=1,
            )
        ):
            values["sequence"] = result[0]["sequence"] + 1

        return self.write(values)

    def action_change_owner(self, new_user_id: int) -> None:
        """Set the given user as owner of the documents in ``self``."""
        self.owner_id = new_user_id

    def action_create_shortcut(
        self, location_user_folder_id: str | None = None
    ) -> DocumentsDocument:
        """Create a shortcut to self in a specific user_folder or as a sibling.

        :param  str | None location_user_folder_id: Optional: where to create the shortcut.
        """
        if not self.ids:
            return self.browse()

        if len(self.folder_id.ids) > 1 and location_user_folder_id is None:
            raise UserError(
                _("A destination is required when creating multiple shortcuts at once.")
            )
        if location_user_folder_id is False:
            raise UserError(_("Ambiguous shortcut target location."))
        if location_user_folder_id is not None:
            # A virtual root resolves to `False` -- "no parent folder" -- which
            # is distinct from the `None` below meaning "no destination given,
            # create the shortcut as a sibling". The guard further down and
            # `_clean_vals_for_user_folder_id` decide what the root means.
            user_folder = self._parse_user_folder(location_user_folder_id)
            location_folder_id = (
                user_folder.folder_id
                if user_folder is not None and user_folder.is_folder
                else False
            )
        else:
            location_folder_id = None

        location = (
            self.browse(location_folder_id)
            if location_folder_id is not None
            else self.folder_id
        )
        if location_folder_id and location.shortcut_document_id:
            return self.action_create_shortcut(str(location.shortcut_document_id.id))

        if location:
            if location.user_permission != "edit":
                raise AccessError(_("You are not allowed to write in this folder."))
        elif location_user_folder_id == UserFolder.COMPANY and not self.env.su:
            # `location` is the empty recordset for the drive roots, so the
            # permission check above never ran for them. Creating a *folder* at
            # the Company root is manager-only (see `create`), and the
            # `sudo().create()` below would otherwise bypass that guard
            # entirely. Files at the Company root stay allowed.
            targets = self.shortcut_document_id | self.filtered(
                lambda d: not d.shortcut_document_id
            )
            if any(t.type == "folder" for t in targets) and not self.env.user.has_group(
                "documents.group_documents_manager"
            ):
                self._raise_company_folder_manager_only()

        # Resolve each input to its ultimate target (``document`` itself when it
        # is not a shortcut) so that we never create a shortcut pointing at
        # another shortcut, while still producing exactly one shortcut per input
        # -- a ``recordset`` union would dedupe targets and desynchronise callers
        # that zip the result against the input (e.g. ``copy``).
        (
            self.shortcut_document_id
            | self.filtered(lambda d: not d.shortcut_document_id)
        ).check_access("read")

        return (
            self.sudo()
            .create(
                [
                    {
                        "user_folder_id": str(location.id)
                        if location
                        else location_user_folder_id,
                        "shortcut_document_id": (
                            target := document.shortcut_document_id or document
                        ).id,
                        **self._shortcut_access_defaults(target),
                        "access_ids": [
                            Command.create(
                                {
                                    "partner_id": access.partner_id.id,
                                    "role": access.role,
                                }
                            )
                            for access in target.access_ids
                            if access.role
                        ],
                        **{
                            field_name: (
                                value.id
                                if isinstance(
                                    (value := target[field_name]), models.Model
                                )
                                else value
                            )
                            for field_name in self._get_shortcuts_copy_fields()
                        },
                    }
                    for document in self
                ]
            )
            .sudo(False)
        )

    def action_view_access_log(self) -> dict:
        """Open this document's access history.

        The log is browsable in its own right (Configuration > Access Log),
        which is what an auditor querying across documents wants; this is the
        other direction -- "what happened to *this* file".
        """
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "documents.documents_access_log_action"
        )
        return action | {
            "display_name": _("Access Log: %s", self.name),
            "domain": [("document_id", "=", self.id)],
            "context": {"search_default_group_partner": 1},
        }

    def toggle_lock(self) -> None:
        """Set a lock user preventing data replacement and archiving by other users.

        Any user with the edit permission can unlock the file.
        """
        self.ensure_one()
        if self.lock_uid:
            self.lock_uid = False
        else:
            self.lock_uid = self.env.uid

    def toggle_favorited(self) -> bool:
        """Toggle the favorited state of the document for the current user."""
        self.ensure_one()
        self.toggle_favorited_multi()
        return self.is_favorited

    def toggle_favorited_multi(
        self,
    ) -> None:  # TODO remove in master and directly modify toggle_favorited
        """Toggle the favorited state of every document in ``self``."""
        # The writes below are `sudo()` -- favouriting is a per-user preference,
        # not a change to the document, so it must work on a document one may
        # only view. That elevation also removed the ONLY check on this
        # RPC-reachable method: `is_favorited` computes `False` for a document
        # the caller cannot read, so those took the "add" branch and any user
        # could plant a `favorited_ids` row on any document id.
        self._check_access_or_raise(
            "read", _("You are not allowed to access these documents.")
        )
        # Partition once and issue two batched m2m writes instead of one write per
        # record (the client calls this on a whole multi-selection).
        favorited = self.filtered("is_favorited").sudo()
        favorited.write({"favorited_ids": [(3, self.env.uid)]})
        (self.sudo() - favorited).write({"favorited_ids": [(4, self.env.uid)]})

    def action_archive(self) -> bool | None:
        """Send the documents in ``self`` and their children to the trash."""
        if not self:
            return None

        # Block directly trashing a document locked by someone else (managers and
        # the lock owner may proceed). Scoped to `self`, not the child cascade, so
        # archiving a folder is not blocked by an unrelated locked descendant.
        if locked_by_other := self._locked_by_other():
            raise UserError(
                _(
                    "“%(name)s” is locked by %(user)s and cannot be sent to "
                    "the trash by another user.",
                    name=locked_by_other[0].name,
                    user=locked_by_other[0].lock_uid.name,
                )
            )

        to_archive_sudo = self._with_descendants_sudo()
        active_documents = to_archive_sudo.filtered(self._active_name).sudo(False)
        if not active_documents:
            return None

        # As document archiving leads to deletion
        active_documents._check_access_or_raise(
            "unlink", self._archive_denied_message()
        )

        active_documents._raise_if_unauthorized_archive()
        active_documents._raise_if_used_folder()
        deletion_date = fields.Date.to_string(
            fields.Date.today() + relativedelta(days=self.get_deletion_delay())
        )
        log_message = _(
            "This file has been sent to the trash and will be deleted forever on the %s",
            deletion_date,
        )
        active_documents._message_log_batch(
            bodies={doc.id: log_message for doc in active_documents}
        )
        # Flag the write `super().action_archive()` issues, so the delegation in
        # `write` lets it through instead of re-entering `action_archive`.
        return super(
            DocumentsDocument,
            active_documents.with_context(documents_archiving=True),
        ).action_archive()

    def action_unarchive(self) -> bool | None:
        """Restore the documents in ``self`` from the trash."""
        self_archived = self.filtered(lambda d: not d.active)
        if not self_archived:
            return None
        archived_top_parent_documents = (
            self.env["documents.document"]
            .sudo()
            .search(
                Domain.AND(
                    (
                        Domain("id", "parent_of", self_archived.ids),
                        Domain("id", "not in", self_archived.ids),
                        Domain("active", "=", False),
                        Domain("folder_id", "=", False)
                        | Domain("folder_id.active", "=", True),
                    )
                )
            )
            .sudo(False)
        )
        if archived_top_parent_documents:
            raise UserError(
                _(
                    "Item(s) you wish to restore are included in archived folders. "
                    "To restore these items, you must restore the following including folders instead:\n"
                    "- %(folders_list)s",
                    folders_list="\n-".join(
                        archived_top_parent_documents.mapped("name")
                    ),
                )
            )  # "Restricted" if not allowed

        # Leave archived children (and descendants) the current user doesn't have access to.
        to_unarchive_candidate_documents = (
            self.env["documents.document"]
            .with_context(active_test=False)
            .search([("id", "child_of", self_archived.ids)])
        )

        seen_documents, to_unarchive_ids = set(), set()

        def add_if_can_be_restored(doc: DocumentsDocument) -> bool:
            if doc in seen_documents or seen_documents.add(doc):
                return doc.id in to_unarchive_ids
            if (
                not doc.folder_id
                or doc.folder_id.sudo().active
                or add_if_can_be_restored(doc.folder_id)
            ):
                to_unarchive_ids.add(doc.id)
                return True
            return False

        for document in to_unarchive_candidate_documents:
            add_if_can_be_restored(document)
        to_unarchive_documents = to_unarchive_candidate_documents.filtered(
            lambda d: d.id in to_unarchive_ids
        )
        log_message = _("This document has been restored.")
        to_unarchive_documents._message_log_batch(
            bodies={doc.id: log_message for doc in to_unarchive_documents}
        )
        return super(DocumentsDocument, to_unarchive_documents).action_unarchive()

    def access_content(self) -> dict:
        """Return an act_url action to open the document content or its URL."""
        self.ensure_one()
        action = {
            "type": "ir.actions.act_url",
            "target": "new",
        }
        if self.url:
            action["url"] = self.url
        elif self.type == "binary":
            action["url"] = f"/documents/content/{quote(self.access_token, safe='')}"
        return action

    def open_resource(self) -> dict | bool:
        """Return an act_window action to open the linked resource, if any."""
        self.ensure_one()
        if self.res_model and self.res_id:
            view_id = self.env[self.res_model].get_formview_id(self.res_id)
            return {
                "res_id": self.res_id,
                "res_model": self.res_model,
                "type": "ir.actions.act_window",
                "views": [[view_id, "form"]],
            }
        return False

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def add_documents_attachment(
        self, res_model: str, res_id: int, is_public: bool = False
    ) -> list[dict]:
        """Create document attachments with optional plugin handling.

        :param str res_model: model name to attach the document to
        :param int res_id: record ID to attach the document to
        :param bool is_public: specify attachment can publicly accessible

        :return: Data of newly created attachments
        :rtype: list[dict]
        """
        # One `copy()` for the whole set. `ir.attachment.copy` creates the rows
        # in a single pass and points every copy sharing an origin store key at
        # it with one write -- an optimization a per-record loop defeats, and
        # content-addressed storage makes those groups real, since the same file
        # uploaded twice already shares one filestore key. It also lets the
        # documents bridge file the copies in a single `_create_document` call
        # instead of one per attachment.
        origins = self.attachment_id
        new_attachments = origins.copy(
            {"res_model": res_model, "res_id": res_id, "public": is_public}
        )
        # `original_id` is the one value that differs per copy, so it cannot
        # travel in the shared default above.
        for origin, copied in zip(origins, new_attachments, strict=True):
            copied.original_id = origin.id

        if is_public:
            # Already a multi-record method -- it collects the rows still
            # needing a token and writes them -- so the per-record loop only
            # re-entered it once per attachment.
            new_attachments.generate_access_token()

        return [attachment._get_media_info() for attachment in new_attachments]

    def _copy_attachment_filter(self, default: dict | None) -> DocumentsDocument:
        if default and "attachment_id" in default:
            return self.env["documents.document"]
        return self.filtered("attachment_id")

    def _copy_with_access(self, default: dict | None) -> DocumentsDocument:
        """Copy documents with their access, assuming access rights were checked before."""
        if not self:
            return self
        res = super().copy(default=default)
        if default and "access_ids" in default:
            return res
        access_vals_list = []
        for doc, doc_copied in zip(self, res, strict=True):
            owner_partner = (
                doc_copied.owner_id.partner_id
            )  # already done at doc_copied creation
            doc_access_to_have = doc.access_ids.filtered("role")
            doc_access_to_create = doc_access_to_have.filtered(
                lambda a, doc_copied=doc_copied, owner_partner=owner_partner: (
                    a.partner_id not in doc_copied.access_ids.partner_id | owner_partner
                )
            )
            access_vals_list += doc_access_to_create.copy_data(
                default={"document_id": doc_copied.id}
            )
        self.env["documents.access"].sudo().create(access_vals_list)
        return res

    def get_deletion_delay(self) -> int:
        """Return the number of days before a trashed document is deleted."""
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param_int("documents.deletion_delay", 30)
        )

    def is_folder_containing_document(self) -> bool:
        """Return whether this folder holds any (non-folder) document below it.

        Used by the folder form view to decide whether deleting the folder must
        warn that files will be trashed. Counting descendants runs in sudo so the
        warning is accurate even for files the current user cannot read, but the
        boolean itself leaks nothing beyond "non-empty".
        """
        self.ensure_one()
        return bool(
            self.env["documents.document"]
            .sudo()
            .search_count(
                [("id", "child_of", self.id), ("type", "!=", "folder")],
                limit=1,
            )
        )

    def _get_is_multipage(self) -> bool | None:
        """Whether the document can be considered multipage, if able to determine.

        :return: `None` if mimetype not handled, `False` if single page or error occurred, `True` otherwise.
        :rtype: bool | None
        """
        decoded = self.attachment_id._get_pdf_raw() if self.attachment_id else None
        if decoded is None:
            return None
        # Avoid warning in tests due to IrActionsReport._pre_render_qweb_pdf rendering pdf as html
        # It is done before even reading the PDF as PdfFileReader emit warning in that case
        if modules.module.current_test and b"<!DOCTYPE html>" in decoded[:32]:
            _logger.info(
                "Skip _get_is_multipage of %r: html content detected in pdf document while in testing mode",
                self.name,
            )
            return False
        stream = io.BytesIO(decoded)
        try:
            return len(PdfFileReader(stream, strict=False).pages) > 1
        except AttributeError:
            raise  # If PyPDF's API changes and the `pages` property isn't there anymore, not if its computation fails.
        except Exception:
            message = (
                "Impossible to count pages in %r. It could be due to a malformed document or a "
                "(possibly known) issue within PyPDF2."
            )
            _logger.warning(message, self.name, exc_info=True)
            return False

    @api.model
    def get_previewable_file_extensions(self) -> set:
        """Return the set of file extensions that can be previewed."""
        return {"bmp", "mp3", "png", "jpg", "jpeg", "pdf", "gif", "txt", "wav"}

    @api.model
    def _get_shortcuts_copy_fields(self) -> set:
        """Fields seeded onto a new shortcut from its target.

        Only fields the shortcut cannot work out for itself belong here.
        Deliberately absent:

        * ``file_size`` -- a readonly stored compute; the value passed here was
          discarded on every shortcut ever created (``_compute_file_size``
          already follows ``shortcut_document_id``), so seeding it was dead code.
        * ``name``, ``file_extension``, ``url_preview_image`` -- resolved by the
          shortcut branches of ``_compute_name_and_preview`` /
          ``_compute_file_extension`` to the same values, including the same
          freeze-on-target-rename behaviour.

        ``is_multipage`` stays: it derives from ``attachment_id``, which a
        shortcut does not have. ``type`` stays: readonly, but not computed, so
        the value does land -- and ``_check_shortcut_fields`` requires it to
        match the target.

        Note that current simple usage in action_create_shortcut supports scalar and m2o fields.
        """
        return {
            "company_id",
            "is_access_via_link_hidden",
            "is_multipage",
            "partner_id",
            "type",
            "url",
        }

    @api.readonly
    @api.model
    def get_document_max_upload_limit(self) -> int | None:
        """Return the maximum allowed upload size in bytes for documents."""
        # Deliberately NOT `get_param_int`: that helper answers "this value or
        # the default", but here an unparsable value must fall through to the
        # NEXT key rather than resolve — collapsing the two would turn a typo in
        # `document.max_fileupload_size` into "no upload limit at all".
        ICP = self.env["ir.config_parameter"].sudo()
        for key in ("document.max_fileupload_size", "web.max_file_upload_size"):
            value = ICP.get_param(key, default=None)
            if value is None:
                continue
            try:
                return int(value) or None
            except ValueError:
                _logger.error("invalid %s: %r", key, value)
        return odoo.http.DEFAULT_MAX_CONTENT_LENGTH

    @api.readonly
    @api.model
    def get_details_panel_res_models(self) -> list:
        """Return the list of models that a document can be linked to via the details panel.

        :rtype: list[str]
        """
        functional_models = [
            "account.move",
            "fleet.vehicle",
            "hr.expense",
            "hr.leave",
            "product.product",
            "project.project",
            "project.task",
            "purchase.order",
            "sale.order",
        ]
        return [
            model
            for model in functional_models
            if (res_model := self.env.get(model)) is not None
            and res_model.has_access("read")
        ]

    @api.model
    def _get_traceback_folder_sudo(self) -> DocumentsDocument:
        # A non-numeric value (the parameter is free-form text an administrator
        # can edit) means "not configured yet": re-provision the folder below
        # rather than raising out of the traceback upload route.
        folder_id = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param_int("documents.support_folder", 0)
        )
        folder_sudo = self.env["documents.document"].sudo().browse(folder_id)
        if not folder_sudo or not folder_sudo.exists():
            folder_sudo = (
                self.env["documents.document"]
                .sudo()
                .create(
                    {
                        "name": self.env._("Support"),
                        "type": "folder",
                        "access_internal": "none",
                        "access_via_link": "none",
                    }
                )
            )
            self.env["ir.config_parameter"].sudo().set_param(
                "documents.support_folder", folder_sudo.id
            )
        return folder_sudo

    def _with_descendants_sudo(self) -> DocumentsDocument:
        """Return ``self`` plus every document below it, archived ones included.

        The subtree both whole-tree transitions operate on: ``unlink`` cascades
        the delete down it, ``action_archive`` cascades the trashing. Read in
        sudo because a user may legitimately delete or trash a folder holding
        documents they cannot see, and with ``active_test=False`` because
        already-trashed children are part of the subtree too. Callers that must
        act as the user drop the elevation with ``.sudo(False)``.
        """
        return (
            self.sudo()
            .with_context(active_test=False)
            .search([("id", "child_of", self.ids)])
        )

    def _get_removable_parent_folders(self) -> DocumentsDocument:
        """Return parent folders that may be deleted once ``self`` is unlinked.

        :return: archived parent folders left without children
        :rtype: recordset of documents.document
        """
        # Fork change (t23528): extracted from unlink() so extending modules
        # can exclude folders that must never be deleted opportunistically
        # (e.g. folders referenced by projects in documents_project).
        #
        # The emptiness/archived test is internal bookkeeping and must be read
        # in sudo: an owner unlinking their own document may have no read access
        # to the parent folder (crash), and a non-sudo ``children_ids`` would
        # only see the *readable* children, so a folder still holding other
        # users' documents could be wrongly considered empty. The set is
        # returned in the caller's environment so the actual deletion in
        # ``unlink()`` stays access-checked (and AccessError-suppressed).
        folders_sudo = self.sudo().with_context(active_test=False).folder_id
        removable_sudo = folders_sudo.filtered(
            lambda folder: (
                not (folder.children_ids - self.sudo())
                and not folder.active
                and folder.id not in self.ids
            )
        )
        return removable_sudo.with_env(self.env)

    @api.model
    def _get_gc_clear_bin_domain(self) -> list:
        deletion_delay = self.get_deletion_delay()
        return [
            ("active", "=", False),
            (
                "write_date",
                "<=",
                fields.Datetime.now() - relativedelta(days=deletion_delay),
            ),
        ]

    def _get_access_action(
        self, access_uid: int | None = None, force_website: bool = False
    ) -> dict:
        self.ensure_one()
        if (
            access_uid
            and not force_website
            and self.active
            and self.env.user.has_group("documents.group_documents_user")
        ):
            url_params = url_encode(
                {
                    "documents_init_document_id": self.id,
                    "view_id": self.env.ref("documents.document_view_kanban").id,
                    "menu_id": self.env.ref("documents.menu_root").id,
                    "folder_id": self.folder_id.id,
                }
            )

            return {
                "type": "ir.actions.act_url",
                "url": f"/odoo/action-documents.document_action?{url_params}",
            }
        return super()._get_access_action(
            access_uid=access_uid, force_website=force_website
        )

    def _get_copy_shortcuts_destinations(
        self, shortcuts: DocumentsDocument, default: dict | None
    ) -> Any:
        """Integrate copy `default` and access rights to return valid destinations for shortcuts to copy."""
        default = default or {}
        folder_id = default.get("folder_id")
        user_folder_id = default.get("user_folder_id")
        prefetch_ids = None
        candidates = {}

        if user_folder := self._parse_user_folder(user_folder_id):
            if user_folder.is_folder:
                candidates[self.browse(user_folder.folder_id)] = shortcuts
            else:
                # A virtual root has no folder to check access on: pass it
                # through for `_clean_vals_for_user_folder_id` to resolve.
                return ((str(user_folder), shortcuts),)
        elif folder_id is not None:
            candidates[self.browse(folder_id)] = shortcuts
        else:
            candidates = shortcuts.grouped("folder_id")
            prefetch_ids = shortcuts.folder_id.ids

        targets_per_destination = defaultdict(self.browse)
        for destination, destination_shortcuts in candidates.items():
            if isinstance(destination, str):
                pass
            elif (
                not self.env.su
                and destination
                and destination.with_prefetch(prefetch_ids).user_permission != "edit"
            ):
                destination = UserFolder.MY
            else:
                destination = str(destination.id)
            targets_per_destination[destination] |= destination_shortcuts
        return targets_per_destination.items()

    @api.model
    def _get_fields_to_recompute(self, depends: list) -> set | list:
        """Get copyable stored-compute fields that need recomputation for the given dependencies."""
        if not depends:
            return []

        fields_to_recompute = set()
        fields_compute_stored = {
            field
            for field in self._fields.values()
            if field.copy and field.store and field.compute
        }
        for field_dependence in (self._fields[depend] for depend in depends):
            fields_dependent = set(self.pool.get_dependent_fields(field_dependence))
            fields_to_recompute |= fields_compute_stored & fields_dependent

        return fields_to_recompute

    def _prepare_create_values(self, vals_list: list[dict]) -> list[dict]:
        old_vals_list = [vals.copy() for vals in vals_list]
        vals_list = super()._prepare_create_values(vals_list)
        folders = self.env["documents.document"].browse(
            v["folder_id"] for v in vals_list if v.get("folder_id")
        )
        users = self.env["res.users"].browse(
            v["owner_id"] for v in vals_list if v.get("owner_id")
        )
        folders.fetch(
            (
                "access_internal",
                "access_via_link",
                "access_ids",
                "active",
                "company_id",
                "owner_id",
            )
        )
        (users | folders.owner_id).fetch(["partner_id"])
        # Resolve read access on every shortcut target in a single ACL pass
        # rather than once per shortcut vals inside the loop below.
        self.browse(
            v["shortcut_document_id"]
            for v in vals_list
            if v.get("shortcut_document_id")
        ).check_access("read")
        vals_list_to_update_linked_record = []
        for vals, old_vals in zip(vals_list, old_vals_list, strict=True):
            owner = self.env["res.users"].browse(
                vals.get("owner_id", self.env.user.active and self.env.user.id)
            )
            if owner and not owner.active:
                _logger.warning(
                    "Documents: Creating document(s) as %s",
                    "superuser"
                    if owner.id == SUPERUSER_ID
                    else f"archived user (id={owner.id})",
                )
                owner = self.env["res.users"]
                vals["owner_id"] = False

            vals_values = {"owner_id": owner.id}
            shortcut_target = self.browse()
            if vals.get("shortcut_document_id"):
                # access already checked in one batch above the loop
                shortcut_target = self.browse(vals["shortcut_document_id"])

            folder = self.env["documents.document"].browse(vals.get("folder_id", False))
            if folder:
                if not folder.active:
                    raise UserError(
                        self.env._(
                            "It is not possible to create documents in an archived folder."
                        )
                    )

                if not shortcut_target:
                    vals_values.update(
                        {
                            "access_via_link": folder.access_via_link,
                            "access_internal": folder.access_internal,
                        }
                    )
                if folder.company_id:
                    vals_values["company_id"] = folder.company_id.id

            if shortcut_target:
                # A shortcut exposes its *target*, not whatever happens to sit in
                # the folder it is dropped into: inheriting the containing
                # folder's `access_via_link` would silently publish a private
                # target. `action_create_shortcut` already derives these from the
                # target; a plain `create()` must do the same.
                vals_values.update(
                    self._shortcut_access_defaults(shortcut_target)
                    | {
                        "is_access_via_link_hidden": shortcut_target.is_access_via_link_hidden,
                    }
                )

            vals.update((k, v) for k, v in vals_values.items() if k not in old_vals)
            # Add folder-inherited members without overriding provided values.
            # Default behaviour (no access_ids provided) is to inherit; a caller
            # opts out by providing an `access_ids` that grants nobody.
            provided_access_ids = self._validated_create_access_commands(
                old_vals.get("access_ids")
            )
            opted_out_of_inheritance = "access_ids" in old_vals and not any(
                command[0] == Command.CREATE for command in provided_access_ids
            )
            if (
                "shortcut_document_id" not in old_vals
                and not opted_out_of_inheritance
                and folder
                and (inherited_access_ids := folder._get_inherited_access_ids_vals())
            ):
                partner_ids = [
                    command[2]["partner_id"]
                    for command in vals["access_ids"] or []
                    if command[0] == Command.CREATE and command[2]
                ]
                access_vals_to_add = [
                    v
                    for v in inherited_access_ids
                    if v["partner_id"] not in partner_ids
                ]
                vals["access_ids"] = list(vals["access_ids"] or []) + [
                    Command.create(access_vals) for access_vals in access_vals_to_add
                ]

            # Ensure owner logged access
            if owner:
                vals["access_ids"] = list(vals["access_ids"] or [])
                for values in vals["access_ids"]:
                    if (
                        values[0] == Command.CREATE
                        and values[2]
                        and values[2]["partner_id"] == owner.partner_id.id
                    ):
                        values[2]["last_access_date"] = fields.Datetime.now()
                        break
                else:
                    vals["access_ids"] += [
                        Command.create(
                            {
                                "partner_id": owner.partner_id.id,
                                "last_access_date": fields.Datetime.now(),
                            }
                        )
                    ]

            # If res_model and res_id are not set, we must get it from the related attachment if set (prepare list)
            if (
                "res_model" not in vals
                and "res_id" not in vals
                and isinstance(vals.get("attachment_id"), int)
            ):
                vals_list_to_update_linked_record.append(vals)

        # For the next step, we need to ensure the related ref is present by getting it from attachment if needed
        if vals_list_to_update_linked_record:
            attachment_by_id = (
                self.env["ir.attachment"]
                .browse(
                    [
                        vals["attachment_id"]
                        for vals in vals_list_to_update_linked_record
                    ]
                )
                .grouped("id")
            )
            for vals in vals_list_to_update_linked_record:
                attachment = attachment_by_id[vals["attachment_id"]]
                vals["res_model"] = (
                    False
                    if attachment.res_model == "documents.document"
                    else attachment.res_model
                )
                vals["res_id"] = (
                    False
                    if attachment.res_model == "documents.document"
                    else attachment.res_id
                )

        # Delegate vals_list update to _prepare_create_values_for_model to add
        # values depending on related record. `groupby` gathers every element
        # sharing a key, not just consecutive ones, so appending group by group
        # RETURNED THE VALS IN A DIFFERENT ORDER than they came in whenever two
        # `res_model`s interleave -- and `create()` hands its records back in
        # whatever order this returns. That breaks the `@api.model_create_multi`
        # contract every caller relies on (`create(vals_list)[i]` is no longer
        # `vals_list[i]`), including this model's own `create`, which zips the
        # result against the attachments it collected beforehand. Group for the
        # per-model call, then scatter the results back into their own slots.
        indexed = list(enumerate(zip(vals_list, old_vals_list, strict=True)))
        prepared_by_position = {}
        for res_model, group in groupby(
            indexed, lambda item: item[1][0].get("res_model")
        ):
            positions = [position for position, __ in group]
            prepared_by_position.update(
                zip(
                    positions,
                    self._prepare_create_values_for_model(
                        res_model,
                        [vals_list[position] for position in positions],
                        [old_vals_list[position] for position in positions],
                    ),
                    strict=True,
                )
            )
        return [prepared_by_position[position] for position in range(len(vals_list))]

    def _prepare_create_values_for_model(
        self, res_model: str | bool, vals_list: list[dict], pre_vals_list: list[dict]
    ) -> list[dict]:
        """Override to add values depending on related model/record."""
        if (
            res_model
            and issubclass(self.pool[res_model], self.pool["documents.mixin"])
            and not self.env.context.get("no_document")
        ):
            return self.env[
                res_model
            ]._prepare_document_create_values_for_linked_records(
                res_model, vals_list, pre_vals_list
            )
        return vals_list

    @api.model
    def _pdf_split(
        self,
        new_files: list | None = None,
        open_files: list | None = None,
        vals: dict | None = None,
    ) -> DocumentsDocument:
        vals = vals or {}
        new_attachments = self.env["ir.attachment"]._pdf_split(
            new_files=new_files, open_files=open_files
        )
        new_documents = self.create(
            [dict(vals, attachment_id=attachment.id) for attachment in new_attachments]
        )
        # Prevent concurrent update error on accessing these documents for the first time on exiting the split tool
        env_partner = self.env.user.partner_id
        documents_not_member = new_documents.filtered(
            lambda d: env_partner not in d.access_ids.partner_id
        )
        self.env["documents.access"].sudo().create(
            [
                {
                    "document_id": doc.id,
                    "partner_id": env_partner.id,
                    "last_access_date": fields.Datetime.now(),
                }
                for doc in documents_not_member
            ]
        )
        return new_documents

    @api.autovacuum
    def _gc_clear_bin(self) -> tuple:
        """Files are deleted automatically from the trash bin after the configured remaining days.

        Reports ``(done, maybe more)`` so the vacuum re-enqueues this until the
        trash is actually drained. Returning ``None`` ran it exactly once per
        daily vacuum, capping expiry at ``limit`` documents a day: any install
        trashing more than that never caught up, and the "deleted forever on
        <date>" the trash promises simply did not happen.
        """
        limit = 1000
        expired = self.search(self._get_gc_clear_bin_domain(), limit=limit)
        removed = len(expired)
        expired.unlink()
        return removed, removed == limit

    # ------------------------------------------------------------
    # VALIDATIONS
    # ------------------------------------------------------------

    def _raise_if_used_folder(self) -> None:
        if folder_ids := self.filtered(lambda d: d.type == "folder").ids:
            company_used_folders_domain = self.env[
                "res.company"
            ]._get_used_folder_ids_domain(folder_ids)
            if (
                self.env["res.company"]
                .sudo()
                .search_count(company_used_folders_domain, limit=1)
            ):
                raise ValidationError(
                    _("Impossible to delete folders used by other applications.")
                )
