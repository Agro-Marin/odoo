"""Server actions pinned onto a folder and offered on its documents.

Two questions, asked in several places and easy to let drift apart: which
server actions may be embedded at all, and which are pinned on the folder a
given document sits in.
"""

from typing import Any

from odoo import _, api, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain


class DocumentsDocument(models.Model):
    _inherit = "documents.document"

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
    def _get_embeddable_server_action_domain(
        self, *, restrict_to_user_groups: bool = True
    ) -> Domain:
        """Wrap `_get_base_server_actions_domain`'s domain to exclude children and actions with invalid children.

        :param bool restrict_to_user_groups: also require the action to be
            visible to the current user. That is right for everything a user
            drives -- listing and pinning -- and **wrong** for anything that
            decides an action is obsolete, because "I cannot see it" and "it
            cannot be run at all" are different questions. The garbage
            collector asked the first and answered the second, so a vacuum run
            by a user lacking a group permanently unlinked every pin of every
            action restricted to it.
        """
        candidate_domain = self._get_base_server_actions_domain()
        if restrict_to_user_groups:
            candidate_domain &= self._server_action_group_domain()
        candidate_actions_sudo = (
            self.env["ir.actions.server"].sudo()._search(candidate_domain)
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
