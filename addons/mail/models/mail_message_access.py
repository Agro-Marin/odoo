import logging
from collections import defaultdict
from collections.abc import Collection

from odoo import api, models
from odoo.api import DomainType
from odoo.exceptions import AccessError, MissingError
from odoo.fields import Domain
from odoo.tools import SQL, Query

from odoo.addons.mail.tools.access_scan import (
    make_document_access_error,
    scan_accessible_query,
)

_logger = logging.getLogger(__name__)


class MailMessage(models.Model):
    _inherit = "mail.message"

    _SEARCH_ACCESS_CHUNK_MIN = 30
    _SEARCH_ACCESS_CHUNK_MAX = 8192

    @api.model
    def _search(
        self,
        domain: DomainType,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
        *,
        bypass_access: bool = False,
        **kwargs,
    ) -> Query:
        if self.env.is_superuser() or bypass_access:
            return super()._search(
                domain, offset, limit, order, bypass_access=True, **kwargs
            )

        if not self.env.user._is_internal():
            domain = self._get_search_domain_non_internal() & Domain(domain)

        self.flush_model(
            [
                "model",
                "res_id",
                "author_id",
                "create_uid",
                "message_type",
                "partner_ids",
            ]
        )
        self.env["mail.notification"].flush_model(["mail_message_id", "res_partner_id"])

        pid = self.env.user.partner_id.id

        return scan_accessible_query(
            self,
            domain,
            offset,
            limit,
            order,
            super()._search,
            fetch=lambda query: self._get_search_access_rows(query, pid),
            allowed=lambda rows: self._get_search_allowed_ids(rows, pid),
            chunk_min=self._SEARCH_ACCESS_CHUNK_MIN,
            chunk_max=self._SEARCH_ACCESS_CHUNK_MAX,
            tiebreak="id desc",
            **kwargs,
        )

    def _get_search_access_rows(self, query: Query, pid: int) -> list[tuple]:
        rel_alias = query.make_alias(self._table, "partner_ids")
        query.add_join(
            "LEFT JOIN",
            rel_alias,
            "mail_message_res_partner_rel",
            SQL(
                "%s = %s AND %s = %s",
                SQL.identifier(self._table, "id"),
                SQL.identifier(rel_alias, "mail_message_id"),
                SQL.identifier(rel_alias, "res_partner_id"),
                pid,
            ),
        )
        notif_alias = query.make_alias(self._table, "notification_ids")
        query.add_join(
            "LEFT JOIN",
            notif_alias,
            "mail_notification",
            SQL(
                "%s = %s AND %s = %s",
                SQL.identifier(self._table, "id"),
                SQL.identifier(notif_alias, "mail_message_id"),
                SQL.identifier(notif_alias, "res_partner_id"),
                pid,
            ),
        )
        return self.env.execute_query(
            query.select(
                SQL.identifier(self._table, "id"),
                SQL.identifier(self._table, "model"),
                SQL.identifier(self._table, "res_id"),
                SQL.identifier(self._table, "author_id"),
                SQL.identifier(self._table, "message_type"),
                SQL.identifier(self._table, "create_uid"),
                SQL(
                    "COALESCE(%s, %s)",
                    SQL.identifier(rel_alias, "res_partner_id"),
                    SQL.identifier(notif_alias, "res_partner_id"),
                ),
            )
        )

    def _get_search_allowed_ids(self, rows: list[tuple], pid: int) -> set[int]:
        direct_allowed = set()
        model_ids = defaultdict(lambda: defaultdict(set))
        for (
            id_,
            model,
            res_id,
            author_id,
            message_type,
            create_uid,
            partner_id,
        ) in rows:
            if pid in (author_id, partner_id) or create_uid == self.env.uid:
                direct_allowed.add(id_)
            elif model and res_id and message_type != "user_notification":
                model_ids[model][res_id].add(id_)
        return direct_allowed | self._find_allowed_doc_ids(model_ids)

    def _get_search_domain_non_internal(self) -> Domain:
        return Domain("message_type", "!=", "comment") | self._get_search_domain_share()

    def _get_search_domain_share(self) -> Domain:
        return (
            Domain("is_internal", "=", False)
            & Domain("subtype_id", "!=", False)
            & Domain("subtype_id.internal", "=", False)
        )

    def _filter_records_for_message_operation(
        self, doc_model: str, doc_res_ids: Collection[int], operation: str
    ) -> models.Model:
        documents_all = (
            self.env[doc_model].with_context(active_test=False).browse(doc_res_ids)
        )
        operation_res_ids = (
            documents_all._mail_group_by_operation_for_mail_message_operation(operation)
        )

        allowed_ids = []
        for record_operation, records in operation_res_ids.items():
            forbidden_doc_ids = set()
            try:
                operation_result = records._check_access(record_operation)
            except MissingError:
                existing = records.exists()
                forbidden_doc_ids = set((records - existing).ids)
                operation_result = existing._check_access(record_operation)
            if operation_result:
                forbidden_doc_ids |= set(operation_result[0]._ids)
            allowed_ids += [
                record.id for record in records if record.id not in forbidden_doc_ids
            ]

        return self.env[doc_model].browse(allowed_ids)

    @api.model
    def _find_allowed_doc_ids(self, model_ids: dict[str, dict]) -> set:
        IrModelAccess = self.env["ir.model.access"]
        allowed_ids = set()
        for doc_model, doc_dict in model_ids.items():
            if not IrModelAccess.check(doc_model, "read", False):
                continue
            allowed = self._filter_records_for_message_operation(
                doc_model, list(doc_dict), "read"
            )
            allowed_ids |= {
                msg_id
                for document_id in allowed.ids
                for msg_id in doc_dict[document_id]
            }
        return allowed_ids

    def _check_access(self, operation: str) -> tuple | None:
        result = super()._check_access(operation)
        if not self:
            return result

        messages = self - result[0] if result else self
        if messages and (forbidden := messages._get_forbidden_access(operation)):
            if result:
                result = (result[0] + forbidden, result[1])
            else:
                result = (forbidden, lambda: forbidden._make_access_error(operation))
        return result

    def _get_forbidden_access(self, operation: str) -> api.Self:
        forbidden = self.browse()

        if not self.env.user._is_internal():
            internal = self._get_forbidden_internal(operation)
            forbidden += internal
            self -= internal
            if not self:
                return forbidden

        remaining = self._get_access_values(operation)
        self._discard_own_messages(remaining, operation)
        if operation == "read":
            self._discard_notified_messages(remaining)
        documents = self._group_ids_by_document(remaining)
        self._discard_accessible_documents(remaining, documents, operation)
        if operation == "create":
            self._discard_notified_parents(remaining)
            self._discard_followed_documents(remaining, documents)

        return forbidden + self.browse(remaining)

    def _get_forbidden_internal(self, operation: str) -> api.Self:
        self.flush_recordset(["is_internal", "subtype_id", "message_type"])
        self.env["mail.message.subtype"].flush_model(["internal"])
        message_type_condition = (
            SQL("message.message_type = 'comment' AND")
            if operation in ("create", "read")
            else SQL.EMPTY
        )
        rows = self.env.execute_query(
            SQL(
                """ SELECT message.id
                    FROM "mail_message" AS message
                    LEFT JOIN "mail_message_subtype" as subtype ON message.subtype_id = subtype.id
                    WHERE %s message.id = ANY (%s)
                        AND (message.is_internal IS TRUE OR message.subtype_id IS NULL OR subtype.internal IS TRUE)
                """,
                message_type_condition,
                self.ids,
            )
        )
        return self.browse(id_ for [id_] in rows)

    def _get_access_values(self, operation: str) -> dict:
        self.flush_recordset(
            [
                "model",
                "res_id",
                "author_id",
                "create_uid",
                "parent_id",
                "message_type",
                "partner_ids",
            ]
        )
        self.env["mail.notification"].flush_model(["mail_message_id", "res_partner_id"])

        if operation in ("read", "write"):
            query = SQL(
                """ SELECT m.id, m.model, m.res_id, m.author_id, m.create_uid, m.parent_id,
                        bool_or(partner_rel.res_partner_id IS NOT NULL OR needaction_rel.res_partner_id IS NOT NULL) AS notified,
                        m.message_type
                    FROM "mail_message" m
                    LEFT JOIN "mail_message_res_partner_rel" partner_rel
                        ON partner_rel.mail_message_id = m.id AND partner_rel.res_partner_id = %(pid)s
                    LEFT JOIN "mail_notification" needaction_rel
                        ON needaction_rel.mail_message_id = m.id AND needaction_rel.res_partner_id = %(pid)s
                    WHERE m.id = ANY(%(ids)s)
                    GROUP BY m.id
                """,
                pid=self.env.user.partner_id.id,
                ids=self.ids,
            )
        elif operation in ("create", "unlink"):
            query = SQL(
                """ SELECT id, model, res_id, author_id, parent_id, message_type
                    FROM "mail_message"
                    WHERE id = ANY(%s)
                """,
                self.ids,
            )
        else:
            raise ValueError(f"Wrong operation name ({operation})")

        return {values["id"]: values for values in self.env.execute_query_dict(query)}

    def _discard_own_messages(self, remaining: dict, operation: str) -> None:
        partner_id = self.env.user.partner_id.id
        for mid, message in list(remaining.items()):
            if operation == "read":
                accessible = (
                    message.get("author_id") == partner_id
                    or message.get("create_uid") == self.env.uid
                )
            elif operation == "write":
                accessible = message.get("author_id") == partner_id
            elif operation == "create":
                accessible = not self._is_thread_message_visible(vals=message)
            else:
                accessible = False
            if accessible:
                remaining.pop(mid, None)

    def _discard_notified_messages(self, remaining: dict) -> None:
        for mid, message in list(remaining.items()):
            if message.get("notified"):
                remaining.pop(mid, None)

    def _group_ids_by_document(self, remaining: dict) -> dict:
        documents = defaultdict(lambda: defaultdict(list))
        for mid, message in remaining.items():
            if (
                message.get("model")
                and message.get("res_id")
                and message.get("message_type") != "user_notification"
                and message["model"] in self.env
            ):
                documents[message["model"]][message["res_id"]].append(mid)
        return documents

    def _discard_accessible_documents(
        self, remaining: dict, documents: dict, operation: str
    ) -> None:
        if not remaining:
            return
        for model, docid_msgids in documents.items():
            allowed_ids = set(
                self._filter_records_for_message_operation(
                    model, list(docid_msgids), operation
                )._ids
            )
            for doc_id, msg_ids in docid_msgids.items():
                if doc_id in allowed_ids:
                    for mid in msg_ids:
                        remaining.pop(mid, None)

    def _discard_notified_parents(self, remaining: dict) -> None:
        if not remaining:
            return
        parent_ids_msg_ids = defaultdict(list)
        for mid, message in remaining.items():
            if message.get("parent_id"):
                parent_ids_msg_ids[message["parent_id"]].append(mid)
        if not parent_ids_msg_ids:
            return
        query = SQL(
            """ SELECT m.id
                FROM "mail_message" m
                JOIN "mail_message_res_partner_rel" partner_rel
                    ON partner_rel.mail_message_id = m.id AND partner_rel.res_partner_id = %s
                WHERE m.id = ANY(%s) """,
            self.env.user.partner_id.id,
            list(parent_ids_msg_ids),
        )
        for [parent_id] in self.env.execute_query(query):
            for mid in parent_ids_msg_ids[parent_id]:
                remaining.pop(mid, None)

    @api.model
    def _filter_records_followed_by_self(
        self, doc_model: str, doc_res_ids: Collection[int]
    ) -> set[int]:
        if not doc_res_ids:
            return set()
        return set(
            self.env["mail.followers"]
            .sudo()
            .search_fetch(
                [
                    ("res_model", "=", doc_model),
                    ("res_id", "in", list(doc_res_ids)),
                    ("partner_id", "=", self.env.user.partner_id.id),
                ],
                ["res_id"],
            )
            .mapped("res_id")
        )

    def _discard_followed_documents(self, remaining: dict, documents: dict) -> None:
        if not remaining:
            return
        for model, docid_msgids in documents.items():
            for res_id in self._filter_records_followed_by_self(model, docid_msgids):
                for mid in docid_msgids[res_id]:
                    remaining.pop(mid, None)

    def _make_access_error(self, operation: str) -> AccessError:
        return make_document_access_error(self, operation)
