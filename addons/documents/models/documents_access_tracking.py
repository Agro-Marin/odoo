import logging
from collections import defaultdict

from odoo import api, fields, models
from odoo.tools import frozendict

_logger = logging.getLogger(__name__)


class DocumentsAccessTracking(models.Model):
    """Queue document access changes for deferred tracking messages."""

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

        self.env.ref("documents.ir_cron_documents_access_tracking")._trigger()

    @api.model
    def _cron_generate_tracking(self) -> None:
        """Drain the queued access-change trackings into chatter messages.

        Two properties matter here, and neither used to hold:

        * **Progress.** The queue is drained in a loop for as long as the cron
          has time, instead of one row per trigger. A single
          ``action_update_access_rights`` over a large folder queues one row per
          ``tracking_batch_size`` documents but triggers the cron once, so with
          one row per run the surplus rows waited for the *monthly* schedule.
        * **Liveness.** A row that cannot be rendered is dropped (and logged)
          rather than left at the head of the queue. Rendering reads records
          referenced by id inside a JSON payload -- a partner deleted between
          the access change and the cron run raised ``MissingError``, and since
          the row is only unlinked *after* a successful render and the search is
          always ordered by id, that one row poisoned the head of the queue
          forever: every later access change stopped being tracked.
        """
        Cron = self.env["ir.cron"]
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
            remaining = self.search_count([])
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
        # The template dereferences ``partner_map.get(key).name``, so a member
        # whose partner no longer exists must not reach it. Drop those entries
        # instead: the rest of the change is still worth reporting.
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
        """Map each member key of ``changes`` to its (still existing) partner.

        Keys are kept verbatim (``fields.Json`` stringifies dict keys, while the
        ``removed`` list keeps ints) because the template looks partners up by
        the very key it iterates over. Partners deleted since the access change
        was queued are simply absent from the mapping -- resolving them lazily
        made the render raise ``MissingError``.
        """
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
