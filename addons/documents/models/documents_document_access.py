"""Who may reach a document, and how that spreads down the tree.

The permission algebra and its propagation, split out of the model proper:
it is the security boundary of the whole app, it is expressed twice (as a
domain the record rules evaluate, and as the level `user_permission`
reports), and keeping those two next to each other is the only way to see
that they still agree.
"""

from collections import defaultdict
from typing import Any

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain
from odoo.tools import SQL

from odoo.addons.documents.tools import UserFolder


class DocumentsDocument(models.Model):
    _inherit = "documents.document"

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

    def _search_user_permission(
        self,
        operator: str,
        value: list | str,
        exclude_ownership: bool = False,
        *,
        company_domains: dict | None = None,
        ignore_link: bool = False,
    ) -> Domain:
        """Return the domain matching documents at the given permission level(s).

        :param bool ignore_link: answer as if the share link had not been
            followed -- every ``access_via_link`` grant, on the document and
            inherited from its folder, is read as ``'none'``. This is what
            :meth:`_get_permission_without_token_multi` needs, and expressing it
            here is what keeps there being ONE implementation of the rules.

        .. note::
            This is an extension point (it backs ``user_permission``'s
            ``search=``), and it takes keyword-only options that have grown
            twice: ``company_domains`` (resolved once by
            :meth:`_compute_user_permission` for both of its searches) and
            ``ignore_link``. An override should therefore take ``**kwargs`` and
            forward them, rather than restate the list -- restating it means the
            next option added here raises ``TypeError`` on every *read* of
            ``user_permission``, which takes the whole Documents UI down while
            ``search()``, which calls positionally, keeps working and hides the
            breakage. They are keyword-only so a subclass adding its own
            positional parameter cannot silently bind one either.
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
            ignore_link=ignore_link,
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
        link_via_parent_domain = (
            Domain.FALSE
            if ignore_link
            else Domain.AND(
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
                "in", ["edit"], company_domains=company_domains, ignore_link=ignore_link
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
        ignore_link: bool = False,
    ) -> Domain:
        """Permission granted *on the document itself*, ignoring inheritance.

        Split out of `_search_user_permission` so the "one level up" clause can
        ask a different question of the parent than of the document.

        :param bool ignore_link: read every ``access_via_link`` as ``'none'``
            (see :meth:`_search_user_permission`).
        """
        company_domains = company_domains or self._permission_company_domains()
        other_company = company_domains["other"]
        allowed_or_no_company = company_domains["allowed_or_none"]
        any_except_disabled_and_archived_company = company_domains[
            "any_except_disabled_and_archived"
        ]

        # Access from membership
        if searched_roles == ["view"]:
            access_level_domain = Domain("role", "=", "view") & (
                Domain.TRUE
                if ignore_link
                else Domain("document_id.access_via_link", "in", ("none", "view"))
            )
            if not ignore_link:
                # A role-less row (an access-date log entry) still carries the
                # document's own link grant.
                access_level_domain |= Domain("role", "=", False) & Domain(
                    "document_id.access_via_link", "=", "view"
                )
        elif searched_roles == ["edit"]:
            access_level_domain = Domain("role", "=", "edit")
            if not ignore_link:
                access_level_domain |= Domain(
                    "document_id.access_via_link", "=", "edit"
                )
        else:
            access_level_domain = Domain("role", "in", ("view", "edit"))
            if not ignore_link:
                access_level_domain |= Domain(
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
                        ignore_link=ignore_link,
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
                internal_domain = Domain("access_internal", "=", "view")
                if not ignore_link:
                    internal_domain &= Domain("access_via_link", "in", ("none", "view"))
            elif searched_roles == ["edit"]:
                internal_domain = Domain("access_internal", "=", "edit")
                if not ignore_link:
                    internal_domain |= Domain("access_internal", "=", "view") & Domain(
                        "access_via_link", "=", "edit"
                    )
            else:
                internal_domain = Domain("access_internal", "in", ("view", "edit"))
            direct_domain |= internal_domain & allowed_or_no_company

        return direct_domain

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

        documents = self._propagation_target_select(
            no_propagation=no_propagation, access=True
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

    def _propagation_target_select(
        self, extra: Domain = Domain.TRUE, *, no_propagation: bool = False, access: bool
    ) -> SQL:
        """The rows a propagating write may touch, as a ``SELECT id``.

        Three invariants have to hold for every such write, and each one used to
        be re-derived at its call site:

        * **never shortcut -> target.** A shortcut mirrors its target, so
          propagation runs one way; writing back up would let a shortcut rewrite
          the document it only points at.
        * **the subtree, or just the roots** when the caller says not to
          propagate.
        * **only what this user may change**, with archived rows included --
          the trash is part of the subtree, and skipping it leaves a document
          that comes back from the trash with stale access.

        The *access* flag picks which propagation rule applies:
        :meth:`_get_access_update_domain` for a sharing change (extensions
        narrow it -- ``documents_spreadsheet`` exempts frozen spreadsheets),
        :meth:`_get_propagation_domain` for anything else. Moving a document to
        another company is not a sharing change, and inheriting the access-only
        carve-outs there would silently skip records.

        :param extra: additional constraints for this particular write
        :param no_propagation: restrict to ``self`` instead of its subtree
        :param access: whether this is an *access* propagation
        :return: the SQL ``SELECT`` the raw statements build their CTE on
        """
        domain = Domain.AND(
            (
                extra,
                Domain("shortcut_document_id", "=", False),
                Domain("id", "in" if no_propagation else "child_of", self.ids),
                self._get_access_update_domain()
                if access
                else self._get_propagation_domain(),
            )
        )
        # `_search`, not a raw query: it is what applies the record rules and
        # resolves `user_permission` through `_search_user_permission`.
        return self.with_context(active_test=False)._search(domain).select()

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

    def _get_permission_without_token(self) -> str:
        self.ensure_one()
        return self._get_permission_without_token_multi()[self]

    def _get_permission_without_token_multi(self) -> dict:
        """Return ``{document: level}`` as if the share link had not been followed.

        Answers a different *question* from :meth:`_compute_user_permission` --
        "what would this user have without the link?" -- but by the same
        *rules*, and now through the same implementation: the permission domain,
        evaluated with ``ignore_link=True``.

        It used to be a second, hand-written encoding of ownership, membership
        and expiry, ``access_internal``, manager elevation and the
        disabled-company guard. Keeping two encodings of one rule set in
        agreement is not something anyone was doing: they had already drifted on
        the folder-link inheritance clause (a document reachable only through
        its parent's link answered ``view`` here and ``none`` there, so
        ``/documents/touch`` reported it "newly accessible" and made the client
        reload on every first visit), and an extension that changed who may
        reach a document had to implement its rule twice -- ``credit_management``
        does exactly that, and got the *other* signature wrong, which took every
        read of ``user_permission`` down.

        Unifying also drops two of the three blind spots the old encoding had:
        the system-administrator blanket grant and the shortcut-owner extension
        are now honoured here too. Only link-blindness remains, which is the
        entire point of the method.
        """
        permission_by_document = dict.fromkeys(self, "none")
        saved = self.filtered(lambda document: isinstance(document.id, int))
        if not saved:
            return permission_by_document

        # Same prerequisites as `_compute_user_permission`: the domain runs in
        # SQL, so pending writes have to be on disk, and archived documents (the
        # trash) still have a level.
        self.flush_model(self._user_permission_domain_fields())
        self.env["documents.access"].flush_model(
            ["document_id", "partner_id", "role", "expiration_date"]
        )
        documents_sudo = (
            self.env["documents.document"].sudo().with_context(active_test=False)
        )
        in_scope = Domain("id", "in", saved.ids)
        company_domains = self._permission_company_domains()
        levels = {}
        for level in ("view", "edit"):
            query = documents_sudo._search(
                in_scope
                & self._search_user_permission(
                    "in",
                    [level],
                    company_domains=company_domains,
                    ignore_link=True,
                )
            )
            levels.update(dict.fromkeys(query.get_result_ids(), level))
        for document in saved:
            permission_by_document[document] = levels.get(document.id, "none")
        return permission_by_document

    def _get_unauthorized_root_document_owners_sudo(self) -> models.Model:
        """Return sudo'ed documents records as only used by system process."""
        return self.mapped("owner_id").sudo().filtered("share")

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
        # `access=False`: a company move is not a sharing change, so it must not
        # inherit the access-only carve-outs extensions add.
        to_update = self._propagation_target_select(
            Domain("id", "in", self.ids) | Domain("company_id", "!=", company_id),
            access=False,
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

    @api.model
    def _validated_create_access_commands(self, access_ids: Any) -> list:
        """Normalize a caller-supplied ``access_ids`` for :meth:`create`.

        A ``documents.access`` row belongs to exactly one document -- the model
        rejects a change of ``document_id`` outright -- so at creation time the
        only meaningful commands are "grant this partner" and "grant nobody".
        ``LINK`` and a non-empty ``SET`` would reparent an existing row; they
        used to reach the inheritance code below, which reads ``command[2]`` as
        a vals dict, and crashed on the ``int``/``list`` those two carry
        (``'int' object is not subscriptable``) -- an HTTP 500 for input the ORM
        otherwise accepts.

        ``UPDATE``/``DELETE``/``UNLINK`` are equally meaningless (a new record
        has no rows to update or drop) and were quietly worse: none of them
        counts as a member grant, so they read as "opted out of inheritance" and
        silently dropped every member the containing folder should have passed
        down.

        :return: the commands, as a list (``False``/``None`` become ``[]``)
        :raise UserError: on any command other than ``CREATE``, ``CLEAR`` or an
            empty ``SET``
        """
        commands = list(access_ids or [])
        for command in commands:
            code = command[0] if isinstance(command, list | tuple) else command
            if code in (Command.CREATE, Command.CLEAR):
                continue
            if code == Command.SET and not command[2]:
                continue
            raise UserError(
                _(
                    "Document access can only be granted at creation "
                    "(Command.create) or cleared; got command %s.",
                    code,
                )
            )
        return commands

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
