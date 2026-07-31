"""The virtual parent: drive roots and the folder tree above a document.

`user_folder_id` is not a column. It is a *presentation* of `folder_id` +
`owner_id` + reachability -- "My Drive", "Company", "Shared with me",
"Recent", "Trash", or a real folder id -- and every consumer used to
re-derive what a given spelling meant. Its compute, its search, and the
normalisation that turns it back into real columns live together here.
"""

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools import SQL

from odoo.addons.documents.tools import UserFolder


class DocumentsDocument(models.Model):
    _inherit = "documents.document"

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
