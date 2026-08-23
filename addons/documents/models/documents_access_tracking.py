import logging
from collections import defaultdict

from odoo import api, fields, models
from odoo.tools import frozendict

_logger = logging.getLogger(__name__)


class DocumentsAccessTracking(models.Model):

    _name = "documents.access.tracking"
    _description = "Document Access Tracking"
    _log_access = False

    changes = fields.Json(string="Changes need to be tracked", required=True)
    documents = fields.Json(string="Impacted Document Ids", required=True)
    user_id = fields.Many2one(
        "res.users",
        string="User",
        default=lambda self: self.env.user,
    )

    @api.model
    def _create_access_tracking(self, changes_by_document_dict: dict) -> None:
        # Nothing changed -> nothing to track, and nothing for the cron to
        # drain. `action_update_access_rights` reaches here unconditionally, so
        # without this an update that changed nothing (the value was already the
        # one asked for, a propagation that matched no row, a dialog saved
        # untouched) still read `documents.tracking_batch_size`, resolved the
        # cron and inserted an `ir_cron_trigger` row -- waking the cron to drain
        # an empty queue. `_trigger` does not de-duplicate, so a bulk sharing
        # pass queued one such row per call.
        if not changes_by_document_dict:
            return
        documents_by_changes = defaultdict(list)
        for document_id, changes in changes_by_document_dict.items():
            documents_by_changes[frozendict(changes)].append(document_id)

        batch_size = int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("documents.tracking_batch_size", "500")
        )
        for changes, documents in documents_by_changes.items():
            self.sudo().create(
                [
                    {
                        "changes": changes,
                        "documents": documents[offset : offset + batch_size],
                        "user_id": self.env.user.id,
                    }
                    for offset in range(0, len(documents), batch_size)
                ]
            )

        cron = self.env.ref(
            "documents.ir_cron_documents_access_tracking", raise_if_not_found=False
        )
        if cron:
            cron.sudo()._trigger()

    @api.model
    def _cron_generate_tracking(self) -> None:
        Cron = self.env["ir.cron"]
        remaining = self.search_count([])
        while tracking := self.search([], limit=1):
            try:
                with self.env.cr.savepoint():
                    tracking._create_message_track()
            except Exception:
                _logger.warning(
                    "Documents: dropping unrenderable access tracking %s",
                    tracking.id,
                    exc_info=True,
                )
            tracking.unlink()
            remaining = max(remaining - 1, 0)
            if Cron._commit_progress(processed=1, remaining=remaining) <= 0:
                return
        Cron._commit_progress(remaining=0)

    def _create_message_track(self) -> None:
        self.ensure_one()
        document_ids = self.env["documents.document"].browse(self.documents)
        if initial_values := self._get_initial_values():
            if "members" in self.changes:
                self._add_pre_commit_members_data()
            document_ids.with_user(self.user_id)._message_track(
                [
                    "access_internal",
                    "access_via_link",
                    "is_access_via_link_hidden",
                ],
                initial_values,
            )
        else:
            body = self._get_members_change_template_body()
            document_ids.with_user(self.user_id)._message_log_batch(
                bodies=dict.fromkeys(document_ids.ids, body)
            )

    def _get_initial_values(self) -> dict:
        self.ensure_one()
        fields_list = [
            "access_internal",
            "access_via_link",
            "is_access_via_link_hidden",
        ]
        common_values = {
            field: self.changes[field] for field in fields_list if field in self.changes
        }
        return {doc_id: common_values for doc_id in self.documents if common_values}

    def _add_pre_commit_members_data(self) -> None:
        self.ensure_one()
        common_body = self._get_members_change_template_body()
        self.env.cr.precommit.data.setdefault(
            "mail.tracking.message.documents.document",
            dict.fromkeys(self.documents, common_body),
        )

    def _get_members_change_template_body(self) -> str:
        self.ensure_one()
        members = self.changes["members"]
        partner_map = self._get_partners_mapping()
        return self.env["ir.qweb"]._render(
            "documents.tracking_access_members_change",
            {
                "created_access": {
                    key: value
                    for key, value in members["added"].items()
                    if key in partner_map
                },
                "updated_access": {
                    key: value
                    for key, value in members["updated"].items()
                    if key in partner_map
                },
                "removed_access": [
                    key for key in members["removed"] if key in partner_map
                ],
                "partner_map": partner_map,
            },
            lang=self.user_id.lang,
            minimal_qcontext=True,
        )

    def _get_partners_mapping(self) -> dict:
        self.ensure_one()
        members_dict = self.changes["members"]
        keys = [
            *members_dict["added"],
            *members_dict["updated"],
            *members_dict["removed"],
        ]
        existing_ids = set(
            self.env["res.partner"].browse(int(key) for key in keys).exists().ids
        )
        partners_by_id = {
            partner.id: partner
            for partner in self.env["res.partner"].browse(existing_ids)
        }
        return {
            key: partners_by_id[int(key)] for key in keys if int(key) in existing_ids
        }
