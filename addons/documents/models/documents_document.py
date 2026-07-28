import base64
import contextlib
import io
import logging
import re
import string
import uuid
from ast import literal_eval
from collections import OrderedDict, defaultdict
from typing import Any
from urllib.parse import quote
from urllib.parse import urlencode as url_encode

import requests
from dateutil.relativedelta import relativedelta

import odoo
from odoo import SUPERUSER_ID, Command, _, api, fields, models, modules
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.fields import Domain
from odoo.libs.filesystem.mimetypes import get_extension
from odoo.tools import SQL, groupby
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

    @api.constrains("type", "alias_name")
    def _check_alias(self) -> None:
        wrong_records = self.filtered(
            lambda d: (d.type != "folder" or d.shortcut_document_id) and d.alias_name
        )
        if wrong_records:
            raise ValidationError(
                _(
                    "The following documents can't have alias: \n- %(records)s",
                    records="\n-".join(wrong_records.mapped("name")),
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

    def _is_documents_manager(self) -> bool:
        """Whether the current user may act as a Documents manager.

        ``env.is_admin()`` is ``su or user._is_admin()``, so a ``sudo()`` call
        answers ``True`` — an explicit contract the alias and company-folder
        guards rely on (see :meth:`create`). Callers that sudo *on behalf of a
        user* must therefore check before elevating.
        """
        return self.env.is_admin() or self.env.user.has_group(
            "documents.group_documents_manager"
        )

    @api.model
    def _raise_company_folder_manager_only(self) -> None:
        """Refuse a non-manager write into the shared Company drive root.

        Raised from every entry point that can land a *folder* there (create,
        write, copy, shortcut creation); one message for one rule.

        :raise AccessError: always
        """
        raise AccessError(_("Only Documents Managers can create in company folder."))

    def _check_access_or_raise(self, operation: str, message: str) -> None:
        """``check_access`` whose denial is reported as *message*.

        ``check_access`` raises a ``UserError`` naming the records it refused,
        which leaks the names of documents the user cannot see; every caller
        that surfaces the failure to a user therefore re-raises an
        ``AccessError`` carrying its own wording instead.

        :raise AccessError: if *operation* is denied on ``self``
        """
        try:
            self.check_access(operation)
        except UserError as error:
            raise AccessError(message) from error

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

    def _log_transition_to_parent_folders(self, body: Any) -> None:
        """Post one chatter message per parent folder about its children in ``self``.

        The trash and restore transitions log the same way — group by folder,
        post as the folder, drop superuser when the actor owns the children —
        and differ only in wording. *body* is called with the rendered document
        names so each caller keeps its own translatable string at its own call
        site (where the extractor can see it).

        :param body: ``callable(names: str) -> str`` building the message body
        """
        for folder, children in self.filtered("folder_id").grouped("folder_id").items():
            folder.sudo(self.env.user in children.owner_id).message_post(
                body=body(", ".join(children.mapped("display_name")))
            )

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
                        lambda names: _(
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
                        lambda names: _(
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

    # `allowed_company_ids`: this reads `folder_id.user_permission`, which is
    # itself company-scoped (see its own `depends_context`). Without it the cache
    # key is too coarse, so a request that touches two company scopes in one
    # transaction reuses the first scope's result: `user_permission` correctly
    # flipped to `edit` while `user_folder_id` stayed `False`, rendering the
    # document as unfiled.
    @api.depends_context("uid", "allowed_company_ids")
    @api.depends("folder_id", "folder_id.user_permission", "owner_id", "active")
    def _compute_user_folder_id(self) -> None:
        SHARED = UserFolder.SHARED if not self.env.user.share else False
        self.user_folder_id = False  # Inaccessible
        active_documents = self.filtered("active")
        (self - active_documents).user_folder_id = UserFolder.TRASH
        for document in active_documents.filtered(
            lambda d: d.user_permission != "none"
        ):
            if document.folder_id:
                if document.folder_id.user_permission != "none":
                    document.user_folder_id = str(document.folder_id.id)
                else:
                    document.user_folder_id = SHARED
            elif self.env.user.share:
                document.user_folder_id = False
            elif not document.owner_id:
                document.user_folder_id = UserFolder.COMPANY
            elif document.owner_id == self.env.user:
                document.user_folder_id = UserFolder.MY  # Root of user's drive
            else:
                document.user_folder_id = SHARED  # Root of another user's drive

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

    @api.depends_context("uid", "allowed_company_ids")
    @api.depends(
        "access_ids",
        "access_internal",
        "access_via_link",
        "owner_id",
        "is_access_via_link_hidden",
        "company_id",
        "folder_id.access_ids",
        "folder_id.access_internal",
        "folder_id.access_via_link",
        "folder_id.owner_id",
        "folder_id.company_id",
        "shortcut_document_id",
        "shortcut_document_owner_id",
        "access_ids.role",
        "access_ids.expiration_date",
    )
    def _compute_user_permission(self) -> None:
        """Derive the permission level from `_search_user_permission`.

        The level used to be recomputed here in Python, in parallel with the
        domain algebra that every record rule evaluates. Keeping two
        implementations of the same rules in agreement turned out to be
        something nobody was doing: they disagreed on link access inherited one
        level up, and on whether an owner is also a "viewer" (see
        `test_documents_permission_algebra`, which enumerates the state space
        and now guards this).

        So there is one implementation -- the domain -- and this reads it. The
        domain never references `user_permission` itself, so evaluating it here
        cannot recurse; it is evaluated with record rules bypassed because those
        rules *are* expressed on `user_permission` and would.
        """
        self.user_permission = "none"

        # Unsaved records have no row for the domain to match. Answer for the
        # record they originate from, and treat a genuinely new one as editable:
        # it is being created by this user, and the create rule is what governs
        # whether that is allowed.
        saved = self.filtered(lambda document: isinstance(document.id, int))
        for document in self - saved:
            document.user_permission = (
                document._origin.user_permission if document._origin else "edit"
            )
        if not saved:
            return

        # `sudo()` here only drops the record rules; `_search_user_permission`
        # keys off `env.user`, `env.companies` and the user's partner, none of
        # which superuser mode changes. `active_test=False` because archived
        # documents (the trash) still need a level.
        # The domain is evaluated in SQL, so everything it reads has to be on
        # disk first. The Python implementation this replaced read the ORM cache
        # and needed no flush -- notably `shortcut_document_owner_id`, a *stored*
        # related field that is still pending recomputation right after its
        # target's owner changes.
        self.flush_model(self._user_permission_domain_fields())
        self.env["documents.access"].flush_model(
            ["document_id", "partner_id", "role", "expiration_date"]
        )

        documents_sudo = (
            self.env["documents.document"].sudo().with_context(active_test=False)
        )
        in_scope = Domain("id", "in", saved.ids)
        # Two questions, not three: "reachable at all" and "editable" -- a viewer
        # is the difference. Asking for `= 'view'` directly would also work, but
        # that domain has to subtract the edit branch, which is strictly more SQL
        # for the same answer.
        #
        # Both are resolved in one round trip. This compute runs on every list,
        # kanban and search-panel render, and `user_folder_id` re-enters it for
        # the parent folders, so a saved round trip here is worth the explicit
        # SQL -- which is bounded: any error in it fails
        # `test_documents_permission_algebra` across 351 cells x 5 kinds of user.
        # Both domains scope companies the same way; resolving that once keeps
        # the cold-cache cost of this compute to a single pass over the user's
        # companies rather than one per domain.
        company_domains = self._permission_company_domains()
        reachable = documents_sudo._search(
            in_scope
            & self._search_user_permission(
                "in", ["view", "edit"], company_domains=company_domains
            )
        )
        editable = documents_sudo._search(
            in_scope
            & self._search_user_permission(
                "in", ["edit"], company_domains=company_domains
            )
        )
        self.env.cr.execute(
            SQL(
                """SELECT reachable.id, reachable.id IN (%(editable)s)
                     FROM (%(reachable)s) AS reachable""",
                editable=editable.select(),
                reachable=reachable.select(),
            )
        )
        levels = {
            document_id: "edit" if is_editable else "view"
            for document_id, is_editable in self.env.cr.fetchall()
        }
        for document in saved:
            document.user_permission = levels.get(document.id, "none")

    @api.depends("datas", "mimetype")
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

    @api.depends_context("uid", "allowed_company_ids")
    @api.depends("folder_id")
    def _compute_available_embedded_actions_ids(self) -> None:
        embedded_actions = self._get_folder_embedded_actions(self.folder_id.ids)
        embedded_actions_per_folder = {
            folder_id: actions.ids for folder_id, actions in embedded_actions.items()
        }
        self.available_embedded_actions_ids = False
        for document in self.filtered(
            lambda d: d.type != "folder" and not d.shortcut_document_id
        ):
            document.available_embedded_actions_ids = embedded_actions_per_folder.get(
                document.folder_id.id, False
            )

    @api.depends(
        "active",
        "user_permission",
        "folder_id.user_permission",
        "owner_id",
        "user_folder_id",
    )
    # `allowed_company_ids`: reads the company-scoped `user_permission` (below).
    @api.depends_context("uid", "allowed_company_ids")
    def _compute_user_can_move(self) -> None:
        active_documents = self.filtered("active")
        (self - active_documents).user_can_move = False
        if self.env.is_admin() or self.env.user.has_group(
            "documents.group_documents_system"
        ):
            active_documents.user_can_move = True
            return
        owned_documents = active_documents.filtered(
            lambda doc: doc.owner_id == self.env.user
        )
        owned_documents.user_can_move = True
        if unowned_documents := active_documents - owned_documents:
            is_manager = self.env.user.has_group("documents.group_documents_manager")
            for document in unowned_documents:
                document.user_can_move = (
                    document.user_permission == "edit"
                    and (
                        not document.folder_id
                        or document.folder_id.user_permission == "edit"
                    )
                    and (is_manager or document.user_folder_id != UserFolder.COMPANY)
                )

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

    @api.model
    def _search_folder_id(self, operator: str, operand: int | list) -> list:
        if operator != "child_of":
            return Domain(Domain("folder_id", operator, operand), internal=True)
        values = {operand} if isinstance(operand, int) else set(operand)
        if len(values) > 1:
            raise UserError(
                _("Only one value can be searched for child of `folder_id`.")
            )
        value = values.pop()
        return self._get_child_of_domain(
            Domain("folder_id", "=", value) | Domain("id", "=", value), value
        )

    def _search_user_folder_id(self, operator: str, operand: str | int | list) -> list:
        """Search domain for user_folder_id virtual folder_id.

        Note that searching in "RECENT" is allowed for practicality w.r.t. webclient
        even though no record will have "RECENT" as computed `user_folder_id`
        """
        if operator not in ("in", "child_of"):
            return NotImplemented
        values = {operand} if isinstance(operand, str) else set(operand)
        if UserFolder.TRASH in values:
            # Would need `active_test=False` in context
            raise UserError(_("Searching on TRASH is not supported."))
        domain_parts = []
        folder_ids = []
        for value in values:
            user_folder = self._parse_user_folder(value)
            if user_folder is None and self.env.user.share:
                domain_parts.append(
                    Domain("folder_id", "=", False) | Domain("folder_id", "not any", [])
                )
            elif user_folder is None:
                domain_parts.append(Domain.FALSE)
            elif user_folder.kind == UserFolder.COMPANY:
                domain_parts.append(
                    Domain("folder_id", "=", False) & Domain("owner_id", "=", False)
                )
            elif user_folder.kind == UserFolder.MY:
                domain_parts.append(
                    Domain("folder_id", "=", False)
                    & Domain("owner_id", "=", self.env.user.id)
                )
            elif user_folder.kind == UserFolder.RECENT:
                domain_parts.append(
                    Domain(
                        "access_ids",
                        "any",
                        Domain("partner_id", "=", self.env.user.partner_id.id)
                        & Domain("last_access_date", "!=", False),
                    )
                )
            elif user_folder.kind == UserFolder.SHARED:
                # For a share user this is deliberately *search-only*, like
                # "RECENT" above: `_compute_user_folder_id` yields False for them
                # (SHARED is bound to False), but the portal webclient searches
                # on it to list what has been shared with the visitor. See the
                # explicit carve-out in
                # `test_compute_and_search_user_folder_id_equal`.
                # Find records without permission on folder_id as directly searching on user_permission = 'none' is not allowed.
                domain_parts.append(
                    Domain("folder_id", "!=", False)
                    & Domain("folder_id", "not any", [])
                    | Domain("folder_id", "=", False)
                    & Domain("owner_id", "not in", [self.env.user.id, False])
                )
            elif user_folder.is_folder:
                folder_ids.append(user_folder.folder_id)
            else:
                # Only TRASH can reach this (rejected above, before the loop);
                # spelled out so a root added later cannot silently fall through
                # and be treated as a folder id.
                raise UserError(_("Searching on %s is not supported.", user_folder))

        if folder_ids:
            # `_compute_user_folder_id` only yields a folder id when that folder
            # is itself accessible, falling back to SHARED otherwise. Without the
            # accessibility leg (`any []` = passes the record rules) a document
            # inside an unreachable folder answered to *both* that folder's id
            # and SHARED, so it showed up in two virtual folders at once.
            domain_parts.append(
                Domain("folder_id", "in", folder_ids) & Domain("folder_id", "any", [])
            )

        domain = Domain.OR(domain_parts)

        if operator == "child_of":
            if len(values) > 1:
                raise UserError(
                    _("Only one value can be searched for children of `user_folder_id`")
                )
            return self._get_child_of_domain(domain, values.pop())
        return domain

    def _search_user_permission(
        self,
        operator: str,
        value: list | str,
        exclude_ownership: bool = False,
        *,
        company_domains: dict | None = None,
    ) -> Domain:
        """Return the domain matching documents at the given permission level(s).

        .. note::
            This is an extension point (it backs ``user_permission``'s
            ``search=``). An override MUST accept **and forward**
            ``company_domains``: :meth:`_compute_user_permission` resolves the
            company-scoping clauses once and passes them by keyword, so an
            override stuck on the older three-argument signature raises
            ``TypeError`` on every *read* of ``user_permission`` while
            ``search()`` -- which calls positionally -- keeps working and hides
            the breakage. Keyword-only here so a subclass adding its own
            positional parameter cannot silently bind it either.
        """
        if self.env.user._is_public():
            return Domain.FALSE
        searched_roles = {"view", "edit", "none"}
        if operator == "in":
            searched_roles.intersection_update(value)
        elif operator == "not in":
            searched_roles.difference_update(value)
        else:
            return NotImplemented

        searched_roles.discard("none")
        if not searched_roles:
            return Domain.FALSE
        searched_roles = list(searched_roles)

        if self.env.user.has_group("documents.group_documents_system"):
            if searched_roles == ["view"]:
                return Domain.FALSE  # System Administrator has "edit" on all documents, so finds none with "view" only.
            # System Administrator should always be able to edit documents from archived companies (even with active_test=False)
            return Domain.OR(
                [
                    Domain("company_id", "in", self.env.companies.ids),
                    Domain("company_id", "not in", self.env.user.company_ids.ids),
                    Domain("company_id.active", "=", False),
                ]
            )

        company_domains = company_domains or self._permission_company_domains()
        any_except_disabled_and_archived_company = company_domains[
            "any_except_disabled_and_archived"
        ]
        direct_domain = self._direct_user_permission_domain(
            searched_roles,
            exclude_ownership=exclude_ownership,
            company_domains=company_domains,
        )
        if exclude_ownership:
            return direct_domain

        # Look one level up for links unless hidden.
        #
        # The parent is tested for *any* permission, not for the level being
        # searched. `_compute_user_permission` grants the child's
        # `access_via_link` as soon as the parent is reachable at all ("if the
        # user can access the parent, they have the link"), so testing the
        # parent at the searched level made the two implementations disagree
        # whenever the levels differed: a folder shared as Viewer holding a
        # document whose link grants Editor, or -- for a manager, who is Editor
        # on anything with `access_internal` set -- almost any link-shared child.
        # Those documents computed to view/edit but matched neither
        # `user_permission = 'view'` nor `= 'edit'`, so they were skipped by
        # every level-specific domain, including `_get_access_update_domain()`
        # (which decides what an access-rights propagation may touch) and the
        # wizards' "find me a folder I can edit" searches.
        link_via_parent_domain = Domain.AND(
            [
                any_except_disabled_and_archived_company,
                [("access_via_link", "in", searched_roles)],
                [("is_access_via_link_hidden", "=", False)],
                [
                    (
                        "folder_id",
                        "any",
                        self._direct_user_permission_domain(
                            ["view", "edit"], company_domains=company_domains
                        ),
                    )
                ],
            ]
        )

        result = direct_domain | link_via_parent_domain

        if searched_roles == ["view"]:
            # `user_permission` holds exactly one level, so "= view" must mean
            # *exactly* view: a document the user can also edit -- because they
            # own it, hold an edit membership, or reach it through an edit link
            # -- is not a viewer document, and `_compute_user_permission` would
            # never label it one.
            #
            # The branches above try to express that exclusivity piecemeal (the
            # membership clause rejects an edit link, the manager clause demands
            # `access_internal = 'none'`), but they miss ownership and any
            # stronger grant arriving through a different clause, so such
            # documents answered *both* "= view" and "= edit". Subtract the edit
            # domain outright instead of patching each branch.
            # Thread the resolved company clauses through: this recursion runs on
            # every "= view" search, and rebuilding them costs a query apiece.
            result &= ~self._search_user_permission(
                "in", ["edit"], company_domains=company_domains
            )

        return result

    @api.model
    def _user_permission_domain_fields(self) -> list:
        """Fields of `documents.document` the permission domain reads in SQL."""
        return [
            "access_internal",
            "access_via_link",
            "active",
            "company_id",
            "folder_id",
            "is_access_via_link_hidden",
            "owner_id",
            "shortcut_document_id",
            "shortcut_document_owner_id",
        ]

    def _permission_company_domains(self) -> dict:
        """The company-scoping clauses of the permission domain, resolved once.

        Each reads ``env.user.company_ids`` under an ``active_test=False``
        context, and a fresh ``with_context`` environment does not share the
        field cache -- so rebuilding them per call cost a query apiece, several
        times per search. Built once and threaded through instead.
        """
        every_company_ids = self.env.user.with_context(
            active_test=False
        ).company_ids.ids
        allowed_company_ids = self.env.companies.ids
        return {
            "other": Domain("company_id", "!=", False)
            & Domain("company_id", "not in", every_company_ids),
            "allowed_or_none": Domain(
                "company_id", "in", [False, *allowed_company_ids]
            ),
            "any_except_disabled_and_archived": Domain(
                "company_id", "in", allowed_company_ids
            )
            | Domain("company_id", "not in", every_company_ids),
        }

    def _direct_user_permission_domain(
        self,
        searched_roles: list,
        exclude_ownership: bool = False,
        company_domains: dict | None = None,
    ) -> Domain:
        """Permission granted *on the document itself*, ignoring inheritance.

        Split out of `_search_user_permission` so the "one level up" clause can
        ask a different question of the parent than of the document. This is the
        domain counterpart of `_get_permission_without_token_multi`.
        """
        company_domains = company_domains or self._permission_company_domains()
        other_company = company_domains["other"]
        allowed_or_no_company = company_domains["allowed_or_none"]
        any_except_disabled_and_archived_company = company_domains[
            "any_except_disabled_and_archived"
        ]

        # Access from membership
        if searched_roles == ["view"]:
            access_level_domain = (
                Domain("role", "=", "view")
                & Domain("document_id.access_via_link", "in", ("none", "view"))
            ) | (
                Domain("role", "=", False)
                & Domain("document_id.access_via_link", "=", "view")
            )
        elif searched_roles == ["edit"]:
            access_level_domain = Domain("role", "=", "edit") | Domain(
                "document_id.access_via_link", "=", "edit"
            )
        else:
            access_level_domain = Domain("role", "in", ("view", "edit")) | Domain(
                "document_id.access_via_link", "!=", "none"
            )
        access_domain = Domain(
            "access_ids",
            "any",
            Domain.AND(
                (
                    access_level_domain,
                    Domain("partner_id", "=", self.env.user.partner_id.id),
                    Domain("expiration_date", "=", False)
                    | Domain("expiration_date", ">", fields.Datetime.now()),
                )
            ),
        )

        # Access from ownership
        if exclude_ownership:
            owner_domain = Domain.FALSE
        else:
            owner_domain = Domain("owner_id", "=", self.env.user.id) & Domain.OR(
                [
                    [("shortcut_document_id", "=", False)],
                    [("shortcut_document_owner_id", "=", self.env.user.id)],
                    # extend permission to edit on shortcuts when otherwise viewer (synced with target)
                    # optimized to avoid recursive call if owner_domain is not going to be used (see below)
                    # or if everything we need is already in `access_domain`
                    self._direct_user_permission_domain(
                        ["view"],
                        exclude_ownership=True,
                        company_domains=company_domains,
                    )
                    if set(searched_roles) == {"edit"}
                    else Domain.FALSE,
                ]
            )
        direct_domain = any_except_disabled_and_archived_company & (
            access_domain
            if "edit" not in searched_roles
            else access_domain | owner_domain
        )

        # Access form access_internal
        if self.env.user.has_group("documents.group_documents_manager"):
            if searched_roles == ["view"]:
                direct_domain &= Domain("access_internal", "=", "none") | other_company
            else:
                direct_domain |= (
                    Domain("access_internal", "in", ("view", "edit"))
                    & allowed_or_no_company
                )
        elif not self.env.user.share:
            if searched_roles == ["view"]:
                internal_domain = Domain("access_internal", "=", "view") & Domain(
                    "access_via_link", "in", ("none", "view")
                )
            elif searched_roles == ["edit"]:
                internal_domain = Domain("access_internal", "=", "edit") | (
                    Domain("access_internal", "=", "view")
                    & Domain("access_via_link", "=", "edit")
                )
            else:
                internal_domain = Domain("access_internal", "in", ("view", "edit"))
            direct_domain |= internal_domain & allowed_or_no_company

        return direct_domain

    def _search_last_access_date_group(
        self, operator: str, operand: list | set
    ) -> list:
        if operator != "in":
            return NotImplemented
        values = set(operand)
        if False in values:
            query = SQL(
                "(%s SELECT document_id FROM last_access_date)",
                self._get_last_access_date_group_cte(),
            )
            no_access_date = [("id", "not in", query)]
            if len(values) > 1:
                values.remove(False)
                # "in [False, X, ...]" means "no access date" OR "in one of the
                # X groups" -- the two leaves must be OR-ed, not AND-ed.
                return [
                    "|",
                    *no_access_date,
                    *self._search_last_access_date_group(operator, values),
                ]
            return no_access_date
        query = SQL(
            """(%s SELECT document_id FROM last_access_date WHERE date = ANY(%s))""",
            self._get_last_access_date_group_cte(),
            list(values),
        )
        return [("id", "in", query)]

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

    def action_delete_from_history(self, attachment_id: int) -> None:
        """Delete a version, promoting the newest remaining one if it was current.

        The write right was only ever enforced downstream, by
        ``ir.attachment.unlink`` and by the ``attachment_id`` write below, so a
        viewer's attempt surfaced as a raw ``AccessError`` naming an attachment
        they cannot see -- rather than this method's own wording, the way its
        twin :meth:`action_restore_version` states it.

        Deleting the *current* version silently swaps the document's content for
        an older one. That is the same content change ``action_restore_version``
        performs and logs; unlogged, "the file is not what it was yesterday and
        the chatter says nothing" was the only trace left.
        """
        self.ensure_one()
        self._check_access_or_raise(
            "write", _("You are not allowed to delete a version of this document.")
        )
        attachment = self.env["ir.attachment"].browse(attachment_id)

        if attachment not in self.previous_attachment_ids and (
            attachment != self.attachment_id or not self.previous_attachment_ids
        ):
            raise UserError(_("You cannot delete this attachment."))

        deleted_name = attachment.name
        if attachment == self.attachment_id:
            promoted = max(
                self.previous_attachment_ids, key=lambda a: (a.create_date, a.id)
            )
            self.attachment_id = promoted
            self.message_post(
                body=_(
                    "Version deleted: “%(deleted)s” removed, “%(promoted)s” is now "
                    "the current version.",
                    deleted=deleted_name,
                    promoted=promoted.name,
                )
            )
        else:
            self.message_post(
                body=_("Version deleted from the history: “%s”.", deleted_name)
            )

        attachment.unlink()

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

    def _is_download_allowed(self) -> bool:
        """Whether the current user may take this document's bytes away.

        A deterrent, not a control, and worth being honest about: the point of
        "view but do not download" is that the content stays *viewable*, so the
        inline preview keeps serving the same bytes and anyone determined can
        keep them. What it stops is the one-click download -- which is what the
        setting is actually asked for, and what every comparable product means
        by it too.

        Editors are exempt: they can replace the content outright, so
        withholding a copy of it from them expresses nothing.
        """
        self.ensure_one()
        target = self.shortcut_document_id or self
        return not target.is_download_blocked or target.user_permission == "edit"

    def _filtered_downloadable(self) -> DocumentsDocument:
        """The subset of ``self`` whose content the current user may download."""
        return self.filtered(lambda document: document._is_download_allowed())

    def action_restore_version(self, attachment_id: int) -> None:
        """Make a previous version the current one again.

        Going back used to require *deleting* the current version -- the only
        code path that promoted an older attachment was
        `action_delete_from_history`, as a side effect, and it always promoted
        the newest one rather than a chosen one. So "revert to what we had on
        Tuesday" meant destroying everything since, one version at a time, and
        left no record that it had happened.

        Restoring is a content change like any other: the version being replaced
        goes into the history (`write` handles that), and the swap is logged.
        """
        self.ensure_one()
        self._check_access_or_raise(
            "write", _("You are not allowed to restore a version of this document.")
        )

        attachment = self.env["ir.attachment"].browse(attachment_id).exists()
        if attachment not in self.previous_attachment_ids:
            raise UserError(_("This version does not belong to this document."))

        replaced = self.attachment_id
        # `write` moves the outgoing attachment into the history and takes the
        # incoming one out of it, which is exactly the swap wanted here.
        self.write({"attachment_id": attachment.id})
        self.message_post(
            body=_(
                "Version restored: “%(restored)s” replaces “%(replaced)s”.",
                restored=attachment.name,
                replaced=replaced.name,
            )
        )

    def _prune_versions(self) -> None:
        """Drop the oldest versions beyond ``documents.max_versions``.

        Every content replacement keeps a full copy of what it replaced, and
        nothing ever removed them: a document edited daily grows a filestore
        blob a day, forever. The limit is opt-in (0, the default, keeps
        everything) because enabling it destroys data -- that has to be an
        administrator's decision, not something an upgrade does silently.
        """
        max_versions = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param_int("documents.max_versions", 0)
        )
        if max_versions <= 0:
            return
        for document in self:
            versions = document.previous_attachment_ids.sorted(
                key=lambda attachment: (attachment.create_date, attachment.id),
                reverse=True,
            )
            if len(versions) > max_versions:
                # sudo: pruning is bookkeeping on content the writer is already
                # replacing; the attachments hang off this document and may not
                # be individually writable by them.
                versions[max_versions:].sudo().unlink()

    def action_update_access_rights(
        self,
        access_internal: str | None = None,
        access_via_link: str | None = None,
        is_access_via_link_hidden: bool | None = None,
        partners: dict | None = None,
        no_propagation: bool = False,
        is_download_blocked: bool | None = None,
    ) -> list | None:
        """Update access to a document and propagate if applicable.

        This method can be called to update the access of internal users, with
        the link, as well as a set of partners and roles to the records in self
        and their children (except shortcuts), and shortcuts pointing to them
        as they are kept synchronized.

        Modifications to internal users and link access are propagated down to
         children until the new value is already present. Note that changes to
         the discoverability(`is_access_via_link_hidden`) are never propagated.
        For partners, all changes are applied to all children regardless of the
        existing rights structure.

        :param str | None access_internal: optional new permission level for internal users
        :param str | None access_via_link: optional new permission level for partners with the link
        :param bool|None is_access_via_link_hidden: optional new value for discoverability
        :param dict[str | int | res.partner(), tuple[str | bool | None, str | datetime | bool | None] partners:
            Mapping of partner(_id) to the tuple:
                role: 'edit', 'view', False (=>delete),
                expiration: datetime string, False (removed/None)
        :param bool no_propagation: whether to propagate rights to sub-folders
        :param bool | None is_download_blocked: optional new value for whether
            viewers may download the content
        """
        if len(self.ids) == 0:
            return None
        self._check_access_or_raise(
            "write", self.env._("You are not allowed to update these access rights.")
        )

        if self.shortcut_document_id:
            raise UserError(
                _(
                    "You can not update the access of a shortcut, update its target instead."
                )
            )

        # Check inputs as we are going to bypass the ORM in the private method(s)
        access_options = {"view", "edit", "none", None}
        hidden_options = {None, True, False}
        role_options = {"edit", "view", False, None}
        incorrect_fields_to_options = {
            **(
                {"is_access_via_link_hidden": hidden_options}
                if is_access_via_link_hidden not in hidden_options
                else {}
            ),
            **(
                {"is_download_blocked": hidden_options}
                if is_download_blocked not in hidden_options
                else {}
            ),
            **(
                {"access_via_link": access_options}
                if access_via_link not in access_options
                else {}
            ),
            **(
                {"access_internal": access_options}
                if access_internal not in access_options
                else {}
            ),
            **(
                {"partners.role": role_options}
                if any(
                    role not in role_options
                    # only the values are inspected; the partner key is not
                    for (role, __) in (partners or {}).values()
                )
                else {}
            ),
        }
        if incorrect_fields_to_options:
            hints = "\n- " + "\n- ".join(
                f"{name}: {options}"
                for name, options in incorrect_fields_to_options.items()
            )
            raise UserError(
                _(
                    "Incorrect values. Use one of the following for the following fields: %(hints)s.)",
                    hints=hints,
                )
            )

        # Resolve member changes BEFORE applying the internal/link access
        # changes. `_action_update_members` targets documents through
        # `_get_access_update_domain()` (= `user_permission == 'edit'`); if we
        # lowered `access_internal` first, a caller whose own edit right comes
        # from that internal access would lose it and the member grants would
        # silently match nothing. Doing members first keeps the intended grants.
        member_changes = None
        if partners:
            partners = {
                self.env["res.partner"].browse(int(partner))
                if isinstance(partner, str | int)
                else partner: (
                    role,
                    fields.Datetime.to_datetime(exp)
                    if exp and isinstance(exp, str)
                    else exp,
                )
                for partner, (role, exp) in (partners or {}).items()
            }
            member_changes = self._action_update_members(
                partners, no_propagation=no_propagation
            )

        changes_by_document_dict = self._action_update_access(
            access_internal,
            access_via_link,
            is_access_via_link_hidden,
            no_propagation=no_propagation,
            is_download_blocked=is_download_blocked,
        )
        if member_changes:
            created_or_updated_access, removed_access = member_changes
            self._update_changes_by_document_dict(
                created_or_updated_access, removed_access, changes_by_document_dict
            )

        self.env["documents.access.tracking"]._create_access_tracking(
            changes_by_document_dict
        )

        return self.mapped("user_permission")

    def _action_update_access(
        self,
        access_internal: str | None,
        access_via_link: str | None,
        is_access_via_link_hidden: bool | None,
        no_propagation: bool = False,
        is_download_blocked: bool | None = None,
    ) -> dict:
        """Update the access on self and children.

        Stop the propagation when the value is already the right one.

        :param str | None access_internal: change the `access_internal` if not None
        :param str | None access_via_link: change the `access_via_link` if not None
        :param bool | None is_access_via_link_hidden: change the `is_access_via_link_hidden` if not None
        :param bool no_propagation: whether to propagate access update to sub-folders
        :param bool | None is_download_blocked: change the `is_download_blocked` if not None
        """
        self.flush_model()
        changes_by_document_dict = defaultdict(dict)
        for field, value in (
            ("access_internal", access_internal),
            ("access_via_link", access_via_link),
            ("is_access_via_link_hidden", is_access_via_link_hidden),
            # Propagated, unlike discoverability: blocking download on a folder
            # is a statement about what it holds. Left on the folder alone it
            # would only stop the folder's own zip while every file inside it
            # stayed one click away.
            ("is_download_blocked", is_download_blocked),
        ):
            if value is None:
                continue

            # never propagate discoverability
            skip_propagation = no_propagation or field == "is_access_via_link_hidden"

            # records that we might need to update
            candidates_domain = Domain(
                [
                    (field, "!=", value),
                    # the update is done only "target -> shortcut",
                    # but not "shortcut -> target"
                    ("shortcut_document_id", "=", False),
                    ("id", "in" if skip_propagation else "child_of", self.ids),
                ]
            )
            candidates_domain &= self._get_access_update_domain()
            candidates_query = self.with_context(active_test=False)._search(
                candidates_domain
            )

            candidates = candidates_query.select(
                *(
                    self._field_to_sql(candidates_query.table, fname, candidates_query)
                    for fname in ("id", "folder_id", "shortcut_document_id", field)
                )
            )

            self.env.cr.execute(
                SQL(
                    """
                WITH RECURSIVE candidates AS (%(candidates)s),
                -- explore the folders
                documents_to_update AS (
                    SELECT id, %(field)s
                      FROM candidates
                     WHERE id = ANY(%(root_ids)s)
                     UNION
                    SELECT child.id, child.%(field)s
                      FROM candidates AS child
                      JOIN documents_to_update AS parent
                        ON child.folder_id = parent.id
                ),
                -- document.shortcut_ids are updated in "SUDO" to stay in sync
                documents_and_shortcuts AS (%(documents_and_shortcuts)s)
                    UPDATE documents_document
                       SET %(field)s = %(value)s
                      FROM documents_and_shortcuts AS doc
                        -- document | document.children_ids | document.shortcut_ids
                     WHERE documents_document.id = doc.id
                 RETURNING doc.id, doc.%(field)s
            """,
                    field=SQL(field),
                    value=value,
                    root_ids=self.ids,
                    candidates=candidates,
                    documents_and_shortcuts=self._shortcuts_union_sql(
                        "documents_to_update", ("id", field)
                    ),
                )
            )

            for id, old_value in self.env.cr.fetchall():
                changes_by_document_dict[id][field] = old_value

        self.invalidate_model(
            [
                "access_internal",
                "access_via_link",
                "is_access_via_link_hidden",
                "is_download_blocked",
                "user_permission",
            ]
        )

        return changes_by_document_dict

    def _action_update_members(
        self, partners: dict, no_propagation: bool = False
    ) -> tuple:
        """Update the members access on all files bellow the current folder.

        :param partners: Partners to add as members / change access
        :param bool no_propagation: whether to propagate members update to sub-folders
        """
        self.env["documents.access"].flush_model()

        partners_to_remove = self.env["res.partner"]
        # {(role, expiration_date): partners}
        values_to_update = defaultdict(lambda: self.env["res.partner"])

        for partner, (role, expiration_date) in partners.items():
            if role is False:
                # remove the members
                partners_to_remove |= partner
            elif role is not None or expiration_date is not None:
                values_to_update[role, expiration_date] |= partner

        # use `_search` to respect access rules and to use `_search_user_permission`
        to_update_domain = Domain(
            [
                (
                    "shortcut_document_id",
                    "=",
                    False,
                ),  # update "target -> shortcuts" but not "shortcut -> target"
                ("id", "in" if no_propagation else "child_of", self.ids),
            ]
        )
        to_update_domain &= self._get_access_update_domain()

        documents = (
            self.with_context(active_test=False)._search(to_update_domain).select()
        )

        created_or_updated_access = []
        for (role, expiration_date), role_partners in values_to_update.items():
            if role not in ("edit", "view"):
                raise UserError(
                    _("Invalid role.")
                )  # The public method would have returned a more insightful message

            update_fields = [SQL("role = %(role)s", role=role)]
            if expiration_date is not None:
                update_fields.append(
                    SQL(
                        "expiration_date = %(expiration_date)s",
                        expiration_date=expiration_date or None,
                    )
                )
            update_fields = SQL(",").join(update_fields)

            self.env.cr.execute(
                SQL(
                    """
                    WITH documents AS (%(documents)s),
                         documents_and_shortcuts AS (%(documents_and_shortcuts)s),
                    existing AS (
                        SELECT document_id, partner_id, role, expiration_date
                          FROM documents_access
                          JOIN documents_and_shortcuts
                            ON document_id = documents_and_shortcuts.id
                           AND partner_id = any(%(partner_ids)s)
                    ),
                    updated_or_created AS (
                        INSERT INTO documents_access (
                                document_id,
                                partner_id,
                                role,
                                expiration_date
                        ) (
                            SELECT DISTINCT ON (doc.id, partner_id) doc.id,
                                   partner_id,
                                   %(role)s,
                                   %(expiration_date)s
                              FROM documents_and_shortcuts AS doc
                      JOIN LATERAL UNNEST(%(partner_ids)s) AS partner_id ON TRUE
                        )
                       ON CONFLICT (document_id, partner_id) DO UPDATE SET %(update_fields)s
                         RETURNING document_id, partner_id, role, expiration_date
                    )
                    SELECT 'existing' as action, * FROM existing
                    UNION ALL
                    SELECT 'upsert' as action, * FROM updated_or_created
                    ORDER BY action ASC
                """,
                    documents=documents,
                    documents_and_shortcuts=self._shortcuts_union_sql("documents"),
                    partner_ids=role_partners.ids,
                    expiration_date=expiration_date or None,
                    role=role,
                    update_fields=update_fields,
                )
            )
            created_or_updated_access += self.env.cr.fetchall()

        removed_access = []
        if partners_to_remove:
            self.env.cr.execute(
                SQL(
                    """
                WITH documents AS (%(documents)s),
                     documents_and_shortcuts AS (%(documents_and_shortcuts)s)
                DELETE FROM documents_access AS access
                      USING documents_and_shortcuts AS doc
                      WHERE access.document_id = doc.id
                        AND access.partner_id = ANY(%(partner_ids)s)
                  RETURNING access.document_id, access.partner_id
            """,
                    documents=documents,
                    documents_and_shortcuts=self._shortcuts_union_sql("documents"),
                    partner_ids=partners_to_remove.ids,
                )
            )
            removed_access = self.env.cr.fetchall()

        self.env["documents.document"].invalidate_model(
            [
                "access_ids",
                "user_permission",
            ]
        )
        self.env["documents.access"].invalidate_model()

        return created_or_updated_access, removed_access

    @api.model
    def action_folder_embed_action(self, folder_id: int, action_id: int) -> list:
        """Enable or disable the action for the given folder.

        :param int folder_id: The folder on which we pin the actions
        :param int action_id: The id of the action to enable
        """
        if (
            not self.env.user.has_group("documents.group_documents_user")
            and not self.env.su
        ):
            raise AccessError(_("You are not allowed to pin/unpin embedded Actions."))
        # The SAME predicate the listing uses, not just the group filter: an
        # action that is pinnable but not listable produces an ir.embedded.actions
        # row `_get_folder_embedded_actions` filters out forever -- invisible in
        # the UI, and un-unpinnable, because this method's own lookup below
        # filters it out too and therefore takes the "create" branch again,
        # stacking a fresh duplicate on every click. Child actions (parent_id
        # set) are the reachable case.
        embeddable_domain = self._get_embeddable_server_action_domain()
        action = (
            self.env["ir.actions.server"]
            .sudo()
            .search(Domain("id", "=", action_id) & embeddable_domain)
        )
        if not action:
            raise UserError(_("This action does not exist."))
        if action.type != "ir.actions.server":
            raise UserError(_("You cannot pin that type of action."))
        folder = self.env["documents.document"].browse(folder_id).sudo().exists()
        if not folder or folder.type != "folder":
            raise UserError(_("You cannot pin an action on that document."))
        if folder.shortcut_document_id:
            return self.action_folder_embed_action(
                folder.shortcut_document_id.id, action_id
            )
        # Pinning/unpinning changes the embedded actions every user of the folder
        # sees, so it requires edit access on the folder -- not merely being a
        # documents user with view access.
        if (
            not self.env.su
            and folder.with_user(self.env.user).user_permission != "edit"
        ):
            raise AccessError(
                _("You are not allowed to pin/unpin actions on this folder.")
            )

        all_embedded_actions_sudo = (
            self.env["ir.embedded.actions"]
            .sudo()
            .search(
                Domain.AND(
                    [
                        self.env["ir.embedded.actions"]
                        .sudo()
                        ._get_documents_embed_base_domain(),
                        [
                            ("action_id", "=", action_id),
                            ("parent_res_id", "=", folder_id),
                        ],
                    ]
                )
            )
        )
        # No second accessibility pass: this search is pinned to the single
        # `action_id` already validated against `_get_embeddable_server_action_domain`
        # above, so re-filtering the rows through a *weaker* predicate (the group
        # domain alone) could only ever let through what the stricter check
        # already accepted. It used to be a copy of the block in
        # `_get_folder_embedded_actions`, which does need it -- that one searches
        # a whole folder's rows.
        if all_embedded_actions_sudo:
            all_embedded_actions_sudo.unlink()
        else:
            # first pinned action should be displayed first
            last_action = self.env["ir.embedded.actions"].search(
                [], order="sequence DESC", limit=1
            )
            embedded_action = self.env["ir.embedded.actions"].create(
                {
                    "name": action.name,
                    "parent_action_id": self.env.ref("documents.document_action").id,
                    "action_id": action.id,
                    "parent_res_model": "documents.document",
                    "parent_res_id": folder_id,
                    "group_ids": self.env.ref("base.group_user").ids,
                    "sequence": last_action.sequence + 1 if last_action else 1,
                }
            )
            action_name_translations = action._fields["name"]._get_stored_translations(
                action
            )
            for lang, translation in action_name_translations.items():
                if self.env["res.lang"]._lang_get(lang):
                    embedded_action.with_context(lang=lang).name = translation

        return self.get_documents_actions(folder_id)

    @api.model
    def action_execute_embedded_action(self, action_id: int) -> Any:
        """Execute an embedded action on context records.

        :param int action_id: id of embedded action to be run on context provided records.
        """
        if self.env.user.share:
            raise AccessError(_("You are not allowed to execute embedded actions."))
        if self.env.context.get("active_model") != "documents.document":
            raise UserError(_("Unavailable action."))
        ids = self.env.context.get(
            "active_ids",
            [self.env.context["active_id"]]
            if self.env.context.get("active_id")
            else [],
        )
        if not ids:
            raise UserError(_("Missing documents reference."))

        embedded_action = self.env["ir.embedded.actions"].browse([action_id])
        if all(
            action_id in document.available_embedded_actions_ids.ids
            for document in self.browse(ids)
        ):
            return (
                self.env["ir.actions.server"]
                .with_context(documents_active_ids=ids)
                .browse(embedded_action.action_id.id)
                .run()
            )

        raise UserError(_("Unavailable action."))

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
        # Build attachment data with conditional plugin parameters
        new_attachments = self.env["ir.attachment"]
        for attachment in self.attachment_id:
            copied = attachment.copy(
                {
                    "res_model": res_model,
                    "res_id": res_id,
                    "public": is_public,
                    "original_id": attachment.id,
                }
            )
            new_attachments |= copied

        # Generate access tokens if needed
        if is_public:
            for attachment in new_attachments:
                attachment.generate_access_token()

        return [attachment._get_media_info() for attachment in new_attachments]

    @api.model
    def _parse_user_folder(self, value) -> UserFolder | None:
        """Parse a `user_folder_id`, reporting a bad one as a `UserError`.

        The parser itself stays free of ORM concerns and raises `ValueError`;
        this is where that becomes a translated, user-facing message.
        """
        try:
            return UserFolder.parse(value)
        except ValueError as error:
            raise UserError(_("Unexpected user_folder_id value %s", value)) from error

    @api.model
    def _clean_vals_for_user_folder_id(
        self, vals: dict, is_create: bool = False
    ) -> None:
        """Update vals to integrate `user_folder_id`.

        This allows to
          * Override context-provided values if `user_folder_id` is defined
          * Handle constraints on moving only on `folder_id` and `owner_id` instead
            of duplicating them for `user_folder_id`
          * Centralize logic about vals vs context defaults

        Note that passing any values for `folder_id` and `owner_id` in vals or context
        will discard default_user_folder_id.

        :param dict vals: Values for record
        :raises UserError: on invalid new `user_folder_id` or conflict with `folder_id`
           or `owner_id` in `vals`
        """
        # Parsed once, up front: `user_folder_id` may arrive as a virtual root, a
        # folder id, or a folder id spelled as a string (which is what the web
        # client sends), and each spelling used to be re-derived further down.
        user_folder = self._parse_user_folder(vals.get("user_folder_id"))
        if user_folder is None:
            if (
                self.env.context.get("default_user_folder_id")
                and "folder_id" not in vals
                and "owner_id" not in vals
                and "default_folder_id" not in self.env.context
                and "default_owner_id" not in self.env.context
            ):
                user_folder = self._parse_user_folder(
                    self.env.context["default_user_folder_id"]
                )
            if user_folder is None:
                return
        # Normalize the wire value so the (unwritten, computed) field and any
        # later reader see the same spelling the parser accepted.
        vals["user_folder_id"] = str(user_folder)

        if user_folder.kind == UserFolder.COMPANY:
            new_vals = {"owner_id": False, "folder_id": False}
            if is_create and "access_internal" not in vals:
                # A brand-new document in the shared Company drive has no owner
                # and no parent folder to grant access from; default it to
                # company-visible so the creator (and internal users) can see
                # what they just created, instead of the field default 'none'
                # which would hide it from everyone but system administrators.
                # Moving an existing document here (is_create=False) keeps its
                # access untouched. Restricted company documents are still
                # possible by passing access_internal explicitly.
                new_vals["access_internal"] = "view"
        elif user_folder.kind == UserFolder.MY:
            if not self.env.user.active:
                raise UserError(_("Inactive user cannot create/move in 'My Drive'."))
            new_vals = {"owner_id": self.env.user.id, "folder_id": False}
        elif user_folder.kind == UserFolder.RECENT:
            raise UserError(_("Documents cannot be created or moved in 'Recent'."))
        elif user_folder.kind == UserFolder.SHARED:
            raise UserError(
                _("Documents cannot be created or moved in 'Shared With Me'.")
            )
        elif user_folder.kind == UserFolder.TRASH:
            raise UserError(_("Documents cannot be created or moved in the trash."))
        else:
            new_vals = {"folder_id": user_folder.folder_id}

        message = _("Conflicting values passed with user_folder_id.")
        if (folder_id := vals.get("folder_id")) and folder_id != new_vals["folder_id"]:
            raise UserError(message)
        if (
            (owner_id := vals.get("owner_id"))
            and "owner_id" in new_vals
            and owner_id != new_vals["owner_id"]
        ):
            raise UserError(message)
        vals.update(new_vals)

    def _compute_mail_alias_domain_count(self) -> None:
        self.mail_alias_domain_count = (
            self.env["mail.alias.domain"].sudo().search_count([])
        )

    # The CTE buckets on `access_ids.last_access_date`, and it filters on the
    # *current* user's partner, so the result is both value- and user-dependent.
    @api.depends("access_ids", "access_ids.last_access_date")
    @api.depends_context("uid")
    def _compute_last_access_date_group(self) -> None:
        # Raw SQL: pending ORM writes on the bucketed column would otherwise be
        # invisible and the compute would report the pre-write bucket.
        self.env["documents.access"].flush_model(["last_access_date"])
        self.env.cr.execute(
            SQL(
                """(%s SELECT document_id, date FROM last_access_date WHERE document_id = ANY(%s))""",
                self._get_last_access_date_group_cte(),
                self.ids,
            )
        )
        values = {
            line["document_id"]: line["date"] for line in self.env.cr.dictfetchall()
        }
        for document in self:
            document.last_access_date_group = values.get(document.id)

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

    @api.model
    def _data_embed_if_records_exist(
        self, folder_xmlid: str, server_action_xmlid: str
    ) -> None:
        if (action := self.env.ref(server_action_xmlid, raise_if_not_found=False)) and (
            folder := self.env.ref(folder_xmlid, raise_if_not_found=False)
        ):
            self.action_folder_embed_action(folder.id, action.id)

    def _embed_action(self, action_id: int) -> DocumentsDocument:
        """Embed a server action on the current folder(s) if not already done."""
        IrEmbeddedActions = self.env["ir.embedded.actions"]
        embedded_actions = self._get_folder_embedded_actions(self.ids)

        new_embedding_folders = self.env["documents.document"]
        for folder in self:
            if (
                action_id
                not in embedded_actions.get(folder.id, IrEmbeddedActions).action_id.ids
            ):
                folder.action_folder_embed_action(folder.id, action_id)
                new_embedding_folders |= folder
        return new_embedding_folders

    @api.model
    def _ensure_user_role_without_propagation(
        self, role: str, documents_per_user: dict
    ) -> None:
        """Set role membership without propagating to children."""
        existing_access = (
            self.env["documents.access"]
            .sudo()
            .search(
                Domain.OR(
                    [
                        ("partner_id", "=", owner.partner_id.id),
                        ("document_id", "in", documents.ids),
                    ]
                    for owner, documents in documents_per_user.items()
                )
            )
        )
        existing_access.role = role
        existing_access_values = {
            (a.partner_id, a.document_id) for a in existing_access
        }
        self.env["documents.access"].sudo().create(
            [
                {
                    "partner_id": owner.partner_id.id,
                    "document_id": document.id,
                    "role": role,
                }
                for owner, documents in documents_per_user.items()
                for document in documents
                if (owner.partner_id, document) not in existing_access_values
            ]
        )

    def _field_to_sql(self, alias: str, fname: str, query: Any = None) -> SQL:
        """Render *fname* as SQL, joining the per-partner access dates on demand.

        ``last_access_date_group`` resolves through a LEFT JOIN rather than a
        correlated subquery so the expression can be grouped on: PostgreSQL 18
        rejects a correlated subquery referencing ungrouped outer columns.

        The join therefore has to be added to a *query*, and without one there
        is nothing to add it to. Returning the alias anyway produced SQL
        referencing a join that was never made -- a syntax error at execution,
        blamed on whatever assembled the statement rather than on the caller
        that omitted the query.

        :raise ValueError: for ``last_access_date_group`` without a *query*
        """
        if fname == "last_access_date_group":
            if query is None:
                msg = (
                    "last_access_date_group needs a query to hang its join on; "
                    "it cannot be rendered as a standalone expression"
                )
                raise ValueError(msg)
            join_alias = f"{alias}__last_access"
            subquery = SQL(
                """(SELECT document_id,
                    %s AS date_group
                    FROM documents_access
                    WHERE partner_id = %s)""",
                self._last_access_date_group_case_sql(),
                self.env.user.partner_id.id,
            )
            condition = SQL(
                "%s = %s",
                SQL.identifier(join_alias, "document_id"),
                SQL.identifier(alias, "id"),
            )
            query.add_join("LEFT JOIN", join_alias, subquery, condition)
            return SQL.identifier(join_alias, "date_group")

        return super()._field_to_sql(alias, fname, query)

    def _get_propagation_domain(self) -> Domain:
        """Documents a propagating write may touch: the ones the user can edit.

        The base rule behind every "walk the subtree and update it" operation
        (:meth:`_action_update_access`, :meth:`_action_update_members`,
        :meth:`_update_company`). Kept separate from
        :meth:`_get_access_update_domain` because that one is an *access*-only
        extension point: ``documents_spreadsheet`` narrows it so a frozen
        spreadsheet's sharing cannot be changed by propagation, which says
        nothing about which company the document belongs to.
        """
        return Domain.TRUE if self.env.su else Domain("user_permission", "=", "edit")

    def _get_access_update_domain(self) -> Domain:
        """Documents an *access* propagation may touch.

        Override to exempt records from inherited access changes; company
        propagation deliberately does not consult this (see
        :meth:`_get_propagation_domain`).
        """
        return self._get_propagation_domain()

    @api.model
    def _shortcuts_union_sql(
        self, source: str, columns: tuple[str, ...] = ("id",), *, include: bool = True
    ) -> SQL:
        """Select *columns* from the *source* CTE, widened with its shortcuts.

        A shortcut mirrors its target, so every propagating write below has to
        reach ``document.shortcut_ids`` too — always in sudo, since keeping the
        two in sync is not the writer's decision to make. The same union was
        spelled out four times, under three different aliases; the copies only
        ever differed in which columns they projected.

        :param str source: name of the CTE holding the target document ids
        :param columns: columns to project (must exist on both sides)
        :param bool include: when ``False``, emit the bare ``SELECT`` with no
            shortcut leg. Clearing a company deliberately leaves shortcuts
            alone — see :meth:`_update_company` and the assertion in
            ``test_documents_multicompany.test_company_propagation``.
        """
        projection = SQL(", ").join(SQL.identifier(column) for column in columns)
        base = SQL("SELECT %s FROM %s", projection, SQL.identifier(source))
        if not include:
            return base
        return SQL(
            """%s
                     UNION
                    SELECT %s
                      FROM documents_document AS shortcut
                      JOIN %s AS shortcut_target
                        ON shortcut_target.id = shortcut.shortcut_document_id""",
            base,
            SQL(", ").join(SQL.identifier("shortcut", column) for column in columns),
            SQL.identifier(source),
        )

    @api.model
    def _server_action_group_domain(self) -> Domain:
        """Domain matching server actions the current user's groups allow.

        A group-less action is available to everyone. Shared by the two places
        that filter embedded actions -- the pin/unpin toggle and the folder
        listing -- which must agree on who may see an action even though they
        otherwise apply different filters.
        """
        return Domain(
            "group_ids", "any", [("id", "in", self.env.user.all_group_ids.ids)]
        ) | Domain("group_ids", "=", False)

    @api.model
    def _get_base_server_actions_domain(self) -> Domain:
        """Return the base domain for actions applicable to documents in the current context.

        !Meant to be wrapped by _get_embeddable_server_action_domain. Override to add validity conditions.
        """
        return Domain.AND(
            [
                [("model_id", "=", self.env["ir.model"]._get_id("documents.document"))],
                [("usage", "in", ("ir_actions_server", "documents_embedded"))],
            ]
        )

    @api.model
    def _get_child_of_domain(self, roots_domain: Domain, value: str | int) -> Domain:
        """Make sure that all intermediate folders are also part of the result."""
        if not isinstance(value, str | int):
            raise UserError(
                _(
                    "Only one string or number value can be searched for documents `child_of`."
                )
            )
        if value == UserFolder.SHARED:
            # Can't use sudo speedup here
            shared_roots = self.with_context(active_test=False).search_fetch(
                roots_domain, ["id"]
            )
            return Domain("id", "child_of", shared_roots.ids)
        candidates, top_level_folders = (
            query.select(
                *(
                    self._field_to_sql(query.table, fname, query)
                    for fname in ("id", "folder_id")
                )
            )
            for query in (
                self.with_context(active_test=False)._search([("type", "=", "folder")]),
                self.with_context(active_test=False)._search(
                    roots_domain & Domain("type", "=", "folder")
                ),
            )
        )
        children = SQL(
            """
        WITH RECURSIVE
            candidates as (%(candidates)s),
            top_level as (%(top_level_folders)s),
            children AS (
                SELECT id
                  FROM top_level
                 UNION ALL
                SELECT c.id
                  FROM candidates c
                  JOIN children f
                    ON c.folder_id = f.id
            )
        SELECT id FROM children
        """,
            candidates=candidates,
            top_level_folders=top_level_folders,
        )
        return roots_domain | Domain("folder_id", "any", children)

    def get_deletion_delay(self) -> int:
        """Return the number of days before a trashed document is deleted."""
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param_int("documents.deletion_delay", 30)
        )

    @api.model
    def check_automation_available(self) -> bool:
        """Return whether the ``base_automation`` module is installed.

        ``ir.module.module`` read is restricted to system users in this fork, but
        every documents user needs this one bit to decide between the real
        "Automations" action and the Studio upsell dialog, so it is exposed
        through a sudo helper rather than a direct (and AccessError-prone) client
        search on ``ir.module.module``.
        """
        return bool(
            self.env["ir.module.module"]
            .sudo()
            .search_count(
                [("name", "=", "base_automation"), ("state", "=", "installed")],
                limit=1,
            )
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

    @api.model
    def get_documents_actions(self, folder_id: int) -> list:
        """Return the available actions and a key to know if the action is embedded on the folder."""
        if not isinstance(folder_id, int):
            raise ValueError("Invalid folder_id")
        folder = self.env["documents.document"].search([("id", "=", folder_id)])
        if not folder:
            raise UserError(_("This folder does not exist or is not accessible."))

        embedded_actions = self._get_folder_embedded_actions(folder.ids)
        embedded_actions = (
            embedded_actions[folder.id].action_id.ids if embedded_actions else []
        )

        actions = (
            self.env["ir.actions.server"]
            .sudo()
            .search(self._get_embeddable_server_action_domain())
        )
        return [
            {
                "id": action.id,
                "name": action.display_name,
                "is_embedded": action.id in embedded_actions,
            }
            for action in actions
        ]

    @api.model
    def _get_embeddable_server_action_domain(self) -> Domain:
        """Wrap `_get_base_server_actions_domain`'s domain to exclude children and actions with invalid children."""
        candidate_actions_sudo = (
            self.env["ir.actions.server"]
            .sudo()
            ._search(
                Domain.AND(
                    [
                        self._get_base_server_actions_domain(),
                        self._server_action_group_domain(),
                    ]
                ),
            )
        )
        return Domain.AND(
            [
                [("id", "in", candidate_actions_sudo)],
                [("parent_id", "=", False)],  # no child action
                [
                    ("child_ids", "not any", [("id", "not in", candidate_actions_sudo)])
                ],  # no invalid child
            ]
        )

    def _get_folder_embedded_actions(self, folder_ids: list[int]) -> dict:
        """Return the enabled actions for the given folder."""
        folders_sudo = (
            self.env["documents.document"]
            .sudo()
            .search(
                [
                    ("id", "in", folder_ids),
                    "|",
                    ("user_permission", "!=", "none"),
                    ("children_ids", "any", [("user_permission", "!=", "none")]),
                ]
            )
        )
        if not folders_sudo:
            return {}
        all_embedded_actions_sudo = (
            self.env["ir.embedded.actions"]
            .sudo()
            .search(
                domain=Domain.AND(
                    [
                        self.env["ir.embedded.actions"]
                        .sudo()
                        ._get_documents_embed_base_domain(),
                        [
                            (
                                "parent_res_id",
                                "in",
                                (folders_sudo + folders_sudo.shortcut_document_id).ids,
                            )
                        ],
                    ]
                ),
                order="sequence",
            )
        )
        # Filtering on action_id.groups_id above is not possible because the orm "considers" action_id
        # to be of the ir.actions.action model, that does not have a groups_id field.
        accessible_server_actions_ids = (
            self.env["ir.actions.server"]
            .sudo()
            .search(
                Domain.AND(
                    [
                        [("id", "in", all_embedded_actions_sudo.action_id.ids)],
                        self._get_embeddable_server_action_domain(),
                    ]
                )
            )
            .ids
        )
        embedded_actions = all_embedded_actions_sudo.filtered(
            lambda e: e.action_id.id in accessible_server_actions_ids
        ).sudo(False)
        # group after ordering by `ir.embedded.actions` sequence
        actions_per_folder = embedded_actions.grouped("parent_res_id")
        targets_to_shortcuts_sudo = folders_sudo.grouped("shortcut_document_id")
        actions_per_shortcut_folder = {
            shortcut_sudo.id: actions
            for target_sudo, shortcuts_sudo in targets_to_shortcuts_sudo.items()
            for shortcut_sudo in shortcuts_sudo
            if (actions := actions_per_folder.get(target_sudo.id))
        }
        return actions_per_folder | actions_per_shortcut_folder

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

    def _get_last_access_date_group_cte(self) -> SQL:
        return SQL(
            """
            WITH last_access_date AS (
                SELECT %s AS date,
                       document_id
                  FROM documents_access
                 WHERE partner_id = %s
            )
        """,
            self._last_access_date_group_case_sql(),
            self.env.user.partner_id.id,
        )

    def _get_permission_without_token(self) -> str:
        self.ensure_one()
        return self._get_permission_without_token_multi()[self]

    def _get_permission_without_token_multi(self) -> dict:
        """Return ``{document: level}`` as if the share link had not been followed.

        The second implementation of the permission rules, and deliberately so
        -- do NOT "unify" it with :meth:`_search_user_permission`. It answers a
        different question: *what would this user have without the link?*

        Enumerating the state space (see
        ``test_every_divergence_traces_to_a_known_blind_spot``) shows it is
        blind to exactly three grants, and nothing else: the document's own
        ``access_via_link`` (the link IS the token, so that one is the point),
        the system-administrator blanket grant that the domain short-circuits on
        and this does not implement at all, and the shortcut-owner extension
        (ownership is excluded for shortcuts below). Any divergence outside
        those three means the two have drifted.

        The overlap is still real -- ownership, membership + expiry,
        ``access_internal``, manager elevation and the disabled-company guard
        are encoded here AND in the domain -- so an extension that changes who
        may reach a document has to implement its rule twice. ``credit_management``
        does exactly that, and got the *other* one's signature wrong, which took
        every read of ``user_permission`` down. If you extend one, extend both,
        and keep this one link-blind.
        """
        permission_by_document = {}
        # Collect already-resolved ids in a set and rebuild the remaining
        # recordset once. Repeated `documents_to_process -= document` inside the
        # loop is O(n^2) recordset reconstruction, and this method backs
        # `_compute_user_permission`, which every kanban/list/search-panel render
        # triggers over the whole folder set.
        resolved_ids = set()
        for document in self:
            exclude_ownership = bool(document.shortcut_document_id)
            is_user_company = (
                document.company_id
                and document.company_id
                in self.env.user.with_context(active_test=False).company_ids
            )
            is_disabled_company = (
                is_user_company and document.company_id not in self.env.companies
            )
            if is_disabled_company:
                permission_by_document[document] = "none"
                resolved_ids.add(document.id)
                continue

            if document.owner_id == self.env.user and not exclude_ownership:
                permission_by_document[document] = "edit"
                resolved_ids.add(document.id)
                continue

            permission_by_document[document] = "none"

        documents_to_process = self.browse(
            doc_id for doc_id in self._ids if doc_id not in resolved_ids
        )
        if not documents_to_process:
            return permission_by_document

        # access with <documents.access>
        access_by_document = self.env["documents.access"]._read_group(
            domain=[
                ("partner_id", "=", self.env.user.partner_id.id),
                ("document_id", "in", documents_to_process.ids),
                "|",
                ("expiration_date", "=", False),
                ("expiration_date", ">", fields.Datetime.now()),
            ],
            groupby=["document_id"],
            aggregates=["id:recordset"],
        )

        # `access` is a singleton, since there can be only 1 access per (document_id, partner_id)
        for document, access in access_by_document:
            if access:
                permission_by_document[document] = (
                    access.role or document.access_via_link
                )

        # access as internal
        for document in documents_to_process:
            if (
                not self.env.user.share
                and permission_by_document[document] != "edit"
                and document.access_internal != "none"
                and (
                    not document.company_id or document.company_id in self.env.companies
                )
            ):
                permission_by_document[document] = (
                    "edit"
                    if self.env.user.has_group("documents.group_documents_manager")
                    else document.access_internal
                )

        return permission_by_document

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

    def _get_unauthorized_root_document_owners_sudo(self) -> models.Model:
        """Return sudo'ed documents records as only used by system process."""
        return self.mapped("owner_id").sudo().filtered("share")

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

    @api.model
    def _get_search_panel_fields(self) -> list:
        """Return the list of fields used by the search panel."""
        search_panel_fields = [
            "access_internal",
            "access_token",
            "access_via_link",
            "active",
            "company_id",
            "description",
            "display_name",
            "user_folder_id",
            "is_access_via_link_hidden",
            "is_favorited",
            "mail_alias_domain_count",
            "owner_id",
            "shortcut_document_id",
            "user_permission",
        ]
        if not self.env.user.share:
            search_panel_fields += [
                "alias_domain_id",
                "alias_name",
                "alias_tag_ids",
                "create_activity_type_id",
                "create_activity_user_id",
                "partner_id",
            ]
        return search_panel_fields

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

    def _get_inherited_access_ids_vals(self) -> list[dict]:
        """Get access values to create when creating a document inside a folder (self).

        :rtype: list[dict]
        :return: vals_list for folder child `access_ids`.
        """
        self.ensure_one()
        vals = [
            {
                "partner_id": access.partner_id.id,
                "role": access.role,
                "expiration_date": access.expiration_date,
            }
            for access in self.access_ids.filtered("role")
            if access.partner_id != self.owner_id.partner_id
        ]
        if self.owner_id:
            vals += [{"partner_id": self.owner_id.partner_id.id, "role": "edit"}]
        return vals

    def _last_access_date_group_case_sql(self) -> SQL:
        """CASE bucketing ``documents_access.last_access_date`` into the UI groups.

        The cutoffs are computed in Python (``fields.Datetime.now()``, naive UTC)
        and passed as parameters rather than using SQL ``NOW() - INTERVAL``: the
        column stores naive UTC, whereas ``NOW()`` on a ``timestamp`` column
        resolves in the database session's timezone, so the two only agree when
        that session runs in UTC. Python cutoffs make the bucketing consistent
        with the ORM clock and deterministic under ``freeze_time``. This is the
        single source shared by the compute, the search and the group-by SQL.
        """
        now = fields.Datetime.now()
        return SQL(
            """(CASE
                   WHEN last_access_date > %s THEN '3_day'
                   WHEN last_access_date > %s THEN '2_week'
                   WHEN last_access_date > %s THEN '1_month'
                   ELSE '0_older'
               END)""",
            now - relativedelta(days=1),
            now - relativedelta(days=7),
            now - relativedelta(months=1),
        )

    def _order_field_to_sql(
        self, alias: str, field_name: str, direction: SQL, nulls: SQL, query: Any
    ) -> SQL:
        if field_name == "last_access_date_group":
            sql_field = SQL(
                "SELECT last_access_date FROM documents_access WHERE partner_id = %s AND document_id = %s",
                self.env.user.partner_id.id,
                SQL.identifier(alias, "id"),
            )
            return SQL("(%s) %s %s", sql_field, direction, nulls)

        if field_name == "is_folder":
            sql_field = SQL("%s != 'folder'", SQL.identifier(alias, "type"))
            return SQL("(%s) %s %s", sql_field, direction, nulls)

        return super()._order_field_to_sql(alias, field_name, direction, nulls, query)

    @api.model
    def _update_changes_by_document_dict(
        self,
        created_or_updated_access: list,
        removed_access: list,
        changes_by_document_dict: dict,
    ) -> None:
        old_values = defaultdict(dict)
        for action, doc, partner, role, exp in created_or_updated_access:
            exp = fields.Date.to_string(exp) or "None"
            partner_dict = changes_by_document_dict.setdefault(doc, {}).setdefault(
                "members", {"added": {}, "updated": {}, "removed": []}
            )
            if action == "upsert":
                if old := old_values[doc].get(partner):
                    partner_dict["updated"][partner] = {
                        "role": (old["role"], role),
                        "expiration_date": (old["expiration_date"], exp),
                    }
                else:
                    partner_dict["added"][partner] = {
                        "role": role,
                        "expiration_date": exp,
                    }
            elif action == "existing":
                old_values[doc][partner] = {
                    "role": role,
                    "expiration_date": exp,
                }
        for doc, partner in removed_access:
            (
                changes_by_document_dict.setdefault(doc, {})
                .setdefault("members", {"added": {}, "updated": {}, "removed": []})[
                    "removed"
                ]
                .append(partner)
            )

    def _update_company(self, company_id: int | bool) -> None:
        """Apply company to documents and children, without stopping (see _action_update_members).

        :param int|bool company_id: Id to set or False
        """
        self.flush_model()
        to_update_domain = Domain.AND(
            (
                Domain("id", "in", self.ids) | Domain("company_id", "!=", company_id),
                # the update is done only "target -> shortcut",
                # but not "shortcut -> target"
                [("shortcut_document_id", "=", False)],
                [("id", "child_of", self.ids)],
                # The BASE propagation rule, not `_get_access_update_domain()`:
                # a company move is not an access change, so it must not inherit
                # the access-only carve-outs extensions add there. Spelling the
                # rule out inline (as this did) silently opted out of the shared
                # helper instead of saying so.
                self._get_propagation_domain(),
            )
        )
        to_update = (
            self.with_context(active_test=False)._search(to_update_domain).select()
        )
        # update shortcuts in sudo to keep them synchronized
        self.env.cr.execute(
            SQL(
                """
                    WITH documents_to_update AS (%(to_update)s),
                    documents_and_shortcuts AS (%(documents_and_shortcuts)s)
                    UPDATE documents_document
                       SET %(field)s = %(value)s
                      FROM documents_and_shortcuts AS doc
                     WHERE documents_document.id = doc.id
                """,
                field=SQL("company_id"),
                value=company_id or None,
                to_update=to_update,
                # Setting a company propagates to shortcuts; CLEARING one does
                # not -- a shortcut keeps its company when the target loses its
                # own (test_documents_multicompany.test_company_propagation).
                documents_and_shortcuts=self._shortcuts_union_sql(
                    "documents_to_update", include=bool(company_id)
                ),
            )
        )

        self.invalidate_model(["company_id", "user_permission"])

    def _notify_get_recipients_groups(
        self,
        message: models.Model,
        model_description: str | None,
        msg_vals: dict | bool = False,
    ) -> list:
        groups = super()._notify_get_recipients_groups(
            message, model_description, msg_vals=msg_vals
        )
        if len(self.ids) != 1:
            return groups

        group_values = {
            "active": True,
            "button_access": {"url": self.access_url},
            "has_button_access": True,
        }
        return [
            (
                "group_documents_document_people_with_access",
                lambda pdata: (
                    (
                        pdata["uid"]
                        and self.with_user(pdata["uid"]).user_permission != "none"
                    )
                    or (
                        pdata["id"]
                        and self.access_via_link != "none"
                        and self.access_ids.filtered(
                            lambda a: a.partner_id.id == pdata["id"] and a.role
                        )
                    )
                ),
                group_values,
            )
        ] + groups

    @api.model
    def message_new(
        self, msg_dict: dict, custom_values: dict | None = None
    ) -> DocumentsDocument:
        """Create a document from an incoming email and its attachments."""
        # When an email comes, create a document with the default values,
        # then let `_message_post_after_hook` create one document per attachment.
        custom_values = custom_values or {}

        folder = self.env["documents.document"].browse(custom_values.get("folder_id"))

        custom_values["name"] = _("Mail: %s", msg_dict.get("subject"))
        if "company_id" not in custom_values:
            custom_values["company_id"] = folder.company_id.id

        if "tag_ids" not in custom_values:
            custom_values["tag_ids"] = folder.alias_tag_ids.ids

        else:
            tags = custom_values["tag_ids"]
            if tags and isinstance(tags[0], list | tuple):
                # we have a list of m2m commands
                if all(len(t) >= 2 and t[0] == Command.LINK for t in tags):
                    tags = [t[1] for t in tags]
                elif len(tags) == 1 and len(tags[0]) == 3 and tags[0][0] == Command.SET:
                    tags = tags[0][2]
                else:  # do not support other commands
                    tags = []

            custom_values["tag_ids"] = (
                self.env["documents.tag"].browse(tags).exists().ids
            )

        custom_values["active"] = False
        return (
            super()
            .message_new(msg_dict, custom_values)
            .with_context(document_message_new=True)
        )

    def _alias_get_creation_values(self) -> dict:
        values = super()._alias_get_creation_values()
        values["alias_model_id"] = self.env["ir.model"]._get("documents.document").id
        if self.id:
            values["alias_defaults"] = literal_eval(self.alias_defaults or "{}")
            values["alias_defaults"] |= {"folder_id": self.id}
        return values

    def message_post(
        self, *, message_type: str = "notification", **kwargs
    ) -> models.Model:
        """Prevent document creation when posting a message with attachment on a document.

        If new documents must be created (ex.: alias on document folder), it will be handled by the
        _message_post_after_hook based on the context variable "document_message_new" (ignoring no_document)
        That variable is set to True by the message_new method (and not set by message_update method).
        """
        return super(
            DocumentsDocument, self.with_context(no_document=True)
        ).message_post(message_type=message_type, **kwargs)

    def _message_post_after_hook(self, message: models.Model, msg_vals: dict) -> Any:
        # If the res model was an attachment and a mail, adds all the custom values of the linked
        # document settings to the attachments of the mail. If it was only a new email converts
        # its body to an attachment for the given document (use case: invoice/receipt sent as an email)
        if message.message_type != "email" or not self.env.context.get(
            "document_message_new"
        ):
            return super()._message_post_after_hook(message, msg_vals)

        m2m_commands = msg_vals["attachment_ids"]
        attachments = self.env["ir.attachment"].browse([x[1] for x in m2m_commands])
        disable_mail_to_document = literal_eval(
            self.env["ir.config_parameter"].get_param(
                "documents.disable_mail_to_document", default="0"
            )
        )
        documents = None

        if attachments:
            self.attachment_id = False
            documents = self.env["documents.document"].create(
                [
                    {
                        **self._message_post_after_hook_template_values(),
                        "name": attachment.name,
                        "attachment_id": attachment.id,
                        "company_id": self.folder_id.company_id.id,
                    }
                    for attachment in attachments
                ]
            )

            for attachment, document in zip(attachments, documents, strict=True):
                attachment.write(
                    {
                        "res_model": "documents.document",
                        "res_id": document.id,
                    }
                )
                sub_message_values = {
                    "author_id": msg_vals.get("author_id"),
                    "body": msg_vals.get("body", ""),
                    "email_from": msg_vals.get("email_from"),
                    "message_type": "email",
                    "subject": msg_vals.get("subject") or self.name,
                    "subtype_id": msg_vals.get("subtype_id"),
                    "subtype_xmlid": msg_vals.get("subtype_xmlid"),
                }
                sub_message_values.pop("model", None)
                sub_message_values.pop("res_id", None)
                sub_message_values.pop("attachment_ids", None)
                document.message_post(**sub_message_values)
        elif not self.attachment_id and not disable_mail_to_document:
            attachment = self.env[
                "ir.attachment"
            ].create(
                {
                    "name": msg_vals.get("subject")
                    or msg_vals.get("email_from", _("email")),
                    "type": "binary",
                    "raw": message.body,
                    "mimetype": "application/documents-email",  # Custom mimetype. Only for preview in Documents
                    "res_model": "documents.document",
                }
            )
            document = self.env["documents.document"].create(
                {
                    **self._message_post_after_hook_template_values(),
                    "attachment_id": attachment.id,
                }
            )
            message.res_id = document.id
            attachment.res_id = document.id
            documents = document

        # Activity settings set through alias_defaults values has precedence over the activity folder settings
        if documents:
            for document in documents:
                if self.create_activity_option:
                    document.documents_set_activity(settings_record=self)
                elif self.folder_id.create_activity_option:
                    document.documents_set_activity(settings_record=self.folder_id)

        return super()._message_post_after_hook(message, msg_vals)

    def _message_post_after_hook_template_values(self) -> dict:
        """Values that will be taken from the document template."""
        return {
            "folder_id": self.folder_id.id,
            "owner_id": self.folder_id.owner_id.id,
            "partner_id": self.partner_id.id,
            "tag_ids": self.tag_ids.ids,
        }

    def documents_set_activity(
        self, settings_record: models.Model | None = None
    ) -> None:
        """Generate an activity based on the fields of settings_record.

        :param settings_record: the record that contains the activity fields.
            settings_record.create_activity_type_id (required)
            settings_record.create_activity_summary
            settings_record.create_activity_note
            settings_record.create_activity_date_deadline_range
            settings_record.create_activity_date_deadline_range_type
            settings_record.create_activity_user_id
        """
        if settings_record and settings_record.create_activity_type_id:
            for record in self:
                activity_vals = {
                    "activity_type_id": settings_record.create_activity_type_id.id,
                    "summary": settings_record.create_activity_summary or "",
                    "note": settings_record.create_activity_note or "",
                }
                if settings_record.create_activity_date_deadline_range > 0:
                    activity_vals["date_deadline"] = fields.Date.context_today(
                        settings_record
                    ) + relativedelta(
                        **{
                            settings_record.create_activity_date_deadline_range_type: settings_record.create_activity_date_deadline_range
                        }
                    )
                if (
                    settings_record._fields.get("create_has_owner_activity")
                    and settings_record.create_has_owner_activity
                    and record.owner_id
                ):
                    user = record.owner_id
                elif (
                    settings_record._fields.get("create_activity_user_id")
                    and settings_record.create_activity_user_id
                ):
                    user = settings_record.create_activity_user_id
                elif settings_record._fields.get("user_id") and settings_record.user_id:
                    user = settings_record.user_id
                else:
                    user = self.env.user
                if user:
                    activity_vals["user_id"] = user.id
                record.activity_schedule(**activity_vals)

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
            # Default behaviour (no access_ids provided) is to inherit. A caller
            # opts out only by explicitly providing an access_ids that resolves to
            # no member (`[]`, `False`, `[Command.set([])]`, `[(6, 0, [])]`). The
            # previous identity test against a bare `Command.set([])` tuple never
            # matched those command-list forms, so the opt-out was ignored.
            provided_access_ids = old_vals.get("access_ids")
            opted_out_of_inheritance = "access_ids" in old_vals and not any(
                command[0] in (Command.CREATE, Command.LINK)
                or (command[0] == Command.SET and command[2])
                # `access_ids` may be provided as ``False``/``[]`` (opt out) or a
                # command list; normalize the non-iterable falsy form.
                for command in (provided_access_ids or [])
            )
            if (
                "shortcut_document_id" not in old_vals
                and not opted_out_of_inheritance
                and folder
                and (inherited_access_ids := folder._get_inherited_access_ids_vals())
            ):
                vals_access_ids_to_check = (
                    vals["access_ids"] if old_vals.get("access_ids") else []
                )
                partner_ids = [val[2]["partner_id"] for val in vals_access_ids_to_check]
                access_vals_to_add = [
                    v
                    for v in inherited_access_ids
                    if v["partner_id"] not in partner_ids
                ]
                vals["access_ids"] += [
                    Command.create(access_vals) for access_vals in access_vals_to_add
                ]

            # Ensure owner logged access
            if owner:
                vals["access_ids"] = vals["access_ids"] or []
                for values in vals["access_ids"]:
                    if (
                        values
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

    @api.model
    def _search_panel_folder_counts(self, model_domain: Domain) -> dict:
        """Count the documents each folder directly holds, for the search panel.

        The generic counter machinery (`_search_panel_domain_image`) can only
        group on a *stored* many2one/selection: fed ``user_folder_id`` -- a
        non-stored computed Char -- it took its "selection field" branch and
        died on ``KeyError: 'selection'``, so ``enable_counters`` was a hard 500
        on this search panel rather than a supported option. The virtual field
        is only a presentation of the stored ``folder_id``, so count on that.

        :return: ``{folder_id: number of matching documents directly inside}``
        """
        return {
            folder.id: count
            for folder, count in self._read_group(
                model_domain & Domain("folder_id", "!=", False),
                groupby=["folder_id"],
                aggregates=["__count"],
            )
        }

    @api.model
    def _search_panel_rollup_folder_counts(self, values_range: dict) -> None:
        """Add each folder's descendant counts to its ancestors, in place.

        `_search_panel_global_counters` walks the ``user_folder_id`` chain, but
        that chain leaves ``values_range`` as soon as a folder sits under a
        virtual root ("MY", "COMPANY", "SHARED"), which is a *string* key it
        would then look up and ``KeyError`` on. Walk the stored ``folder_id``
        chain instead: it is an id or ``False``, and it terminates naturally.
        """
        parent_by_folder = {
            folder.id: folder.folder_id.id for folder in self.browse(values_range)
        }
        local_counts = {
            folder_id: values["__count"] for folder_id, values in values_range.items()
        }
        for folder_id, count in local_counts.items():
            if not count:
                continue
            seen = {folder_id}
            parent_id = parent_by_folder.get(folder_id)
            # `seen` guards against a parent cycle, which the DB does not
            # prevent across several rows (only `folder_id <> id` is enforced).
            while parent_id and parent_id not in seen:
                seen.add(parent_id)
                if parent_id in values_range:
                    values_range[parent_id]["__count"] += count
                parent_id = parent_by_folder.get(parent_id)

    @api.model
    def search_panel_select_range(self, field_name: str, **kwargs) -> dict:
        """Return the search panel range values, with virtual folder roots."""

        def convert_user_folder_ids_to_int(vals: dict) -> None:
            """Key the category tree on the parent's id where there is one.

            The client matches a node's parent by *id*, so a real folder has to
            come back as an ``int`` while the virtual roots stay strings.
            """
            user_folder = self._parse_user_folder(vals["user_folder_id"])
            if user_folder is not None and user_folder.is_folder:
                vals["user_folder_id"] = user_folder.folder_id

        if field_name == "user_folder_id":
            enable_counters = kwargs.get("enable_counters", False)
            search_panel_fields = self._get_search_panel_fields()
            domain = Domain("type", "=", "folder")

            if unique_folder_id := self.env.context.get("documents_unique_folder_id"):
                values = self.env["documents.document"].search_read(
                    domain & Domain("folder_id", "child_of", unique_folder_id),
                    search_panel_fields,
                )
                for record in values:
                    convert_user_folder_ids_to_int(record)
                    if record["id"] == unique_folder_id:
                        record["user_folder_id"] = False  # Set as root
                return {
                    "parent_field": "user_folder_id",
                    "values": values,
                }

            records = self.env["documents.document"].search_read(
                domain, search_panel_fields
            )
            alias_tag_data = {}
            if not self.env.user.share:
                alias_tag_ids = {
                    alias_tag_id
                    for rec in records
                    for alias_tag_id in rec["alias_tag_ids"]
                }
                alias_tag_data = {
                    alias_tag["id"]: {
                        "id": alias_tag.id,
                        "color": alias_tag.color,
                        "display_name": alias_tag.display_name,
                    }
                    for alias_tag in self.env["documents.tag"].browse(alias_tag_ids)
                }
            local_counts = {}
            if enable_counters:
                model_domain = Domain.AND(
                    [
                        kwargs.get("search_domain", []),
                        kwargs.get("category_domain", []),
                        kwargs.get("filter_domain", []),
                    ]
                )
                local_counts = self._search_panel_folder_counts(model_domain)

            # Read the targets in batch
            targets = self.browse(
                r["shortcut_document_id"][0]
                for r in records
                if r["shortcut_document_id"]
            )
            targets_user_permission = {t.id: t.user_permission for t in targets}

            values_range = OrderedDict()
            for record in records:
                record_id = record["id"]
                convert_user_folder_ids_to_int(record)
                if not self.env.user.share:
                    record["alias_tag_ids"] = [
                        alias_tag_data[tag_id] for tag_id in record["alias_tag_ids"]
                    ]
                if enable_counters:
                    record["__count"] = local_counts.get(record_id, 0)
                if record["shortcut_document_id"]:
                    record["target_user_permission"] = targets_user_permission[
                        record["shortcut_document_id"][0]
                    ]
                values_range[record_id] = record

            if enable_counters:
                self._search_panel_rollup_folder_counts(values_range)

            special_roots = []
            if not self.env.user.share:
                special_roots = [
                    {
                        "bold": True,
                        "childrenIds": [],
                        "parentId": False,
                        "user_permission": "edit",
                    }
                    | values
                    for values in [
                        {
                            "display_name": _("Company"),
                            "id": UserFolder.COMPANY,
                            "description": _("Common roots for all company users."),
                            "user_permission": "edit"
                            if self.env.user.has_group(
                                "documents.group_documents_manager"
                            )
                            else "view",
                        },
                        {
                            "display_name": _("My Drive"),
                            "id": UserFolder.MY,
                            "user_permission": "edit",
                            "description": _("Your individual space."),
                        },
                        {
                            "display_name": _("Shared with me"),
                            "id": UserFolder.SHARED,
                            "description": _(
                                "Additional documents you have access to."
                            ),
                        },
                        {
                            "display_name": _("Recent"),
                            "id": UserFolder.RECENT,
                            "description": _("Recently accessed documents."),
                        },
                    ]
                ]
                if not self.env.context.get("documents_search_panel_no_trash"):
                    special_roots.append(
                        {
                            "display_name": _("Trash"),
                            "id": UserFolder.TRASH,
                            "description": _(
                                "Items in trash will be deleted forever after %s days.",
                                self.get_deletion_delay(),
                            ),
                        }
                    )

            return {
                "parent_field": "user_folder_id",
                "values": list(values_range.values()) + special_roots,
            }

        return super().search_panel_select_range(field_name, **kwargs)

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

    def _cannot_create_sibling(self) -> bool:
        """Return whether the user is not allowed to create in the same folder, used for copy."""
        self.ensure_one()
        if self.env.su:
            return False
        if self.folder_id:
            # do not check edit access rule, to allow copying in root company folders
            return self.folder_id.user_permission != "edit"
        return (
            # allow the manager to copy root folder without moving them to his drive
            not self.env.user.has_group("documents.group_documents_manager")
            # anyone can copy in one's drive
            and self.owner_id != self.env.user
        )

    def _is_company_root_folder(self) -> bool:
        self.ensure_one()
        return self.type == "folder" and not self.folder_id and not self.owner_id

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

    @api.model
    def _archive_denied_message(self) -> str:
        """The one wording for "you may not send these to the trash".

        Both halves of the archive gate raise it -- the ``unlink`` ACL check and
        the containing-folder check that runs straight after -- and they were two
        copies of the same literal, so a reworded one would have drifted from its
        twin (and doubled the translation entry).
        """
        return _("You do not have sufficient access rights to delete these documents.")

    def _raise_if_unauthorized_archive(self) -> None:
        """Check that the user is owner of documents or has edit permission on the containing folder."""
        if self.env.su:
            return
        unowned_documents = self.filtered(
            lambda d: d.active and d.owner_id != self.env.user
        )
        # NOTE: a document sitting at a drive root has no parent folder to
        # authorize against, so only the `unlink` record rule
        # (`user_permission = 'edit'`) applies to it. That is deliberate --
        # `test_documents_access.test_archiving_with_children` relies on an
        # explicit edit permission on a root folder being enough to trash it.
        # The privilege escalation that used to exploit it (moving a document
        # to a root one does not control, then trashing it) is closed in
        # `write` instead, where the move itself is now refused.
        if any(
            folder.user_permission != "edit" for folder in unowned_documents.folder_id
        ):
            raise UserError(self._archive_denied_message())
