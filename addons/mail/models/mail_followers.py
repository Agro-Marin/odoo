import itertools
import typing
from collections import defaultdict
from typing import Literal, Self

from psycopg.errors import UniqueViolation

from odoo import Command, api, fields, models
from odoo.api import ValuesType

from odoo.addons.mail.tools.discuss import Store, StoreFieldsInput

if typing.TYPE_CHECKING:
    from .mail_message_subtype import MailMessageSubtype
    from .res_partner import ResPartner

_RECIPIENT_USER_LATERAL = """
 LEFT JOIN LATERAL (
        SELECT users.id AS uid,
               users.share AS share,
               users.notification_type AS notification_type,
               ARRAY_AGG(groups_rel.gid) FILTER (WHERE groups_rel.gid IS NOT NULL) AS groups
          FROM res_users users
     LEFT JOIN res_groups_users_rel groups_rel ON groups_rel.uid = users.id
         WHERE users.partner_id = partner.id AND users.active
      GROUP BY users.id
      ORDER BY users.share ASC NULLS LAST, users.id ASC
         FETCH FIRST ROW ONLY
         ) sub_user ON TRUE"""

_RECIPIENT_PARTNER_COLUMNS = """
           partner.id AS pid,
           partner.active AS active,
           partner.email_normalized AS email_normalized,
           partner.lang AS lang,
           partner.name AS name,
           partner.partner_share AS pshare,
           sub_user.uid AS uid,
           COALESCE(sub_user.share, FALSE) AS ushare,
           COALESCE(sub_user.notification_type, 'email') AS notif,
           sub_user.groups AS groups"""

_RECIPIENT_FOLLOWERS_QUERY = f"""
    WITH sub_followers AS (
        SELECT fol.partner_id AS pid,
               fol.res_id AS res_id,
               TRUE AS is_follower,
               subrel.mail_followers_id IS NOT NULL AS subtype_follower,
               subrel.mail_followers_id IS NOT NULL
               AND COALESCE(
                       (SELECT subtype.internal
                          FROM mail_message_subtype subtype
                         WHERE subtype.id = %(subtype_id)s),
                       FALSE
                   ) AS internal
          FROM mail_followers fol
     LEFT JOIN mail_followers_mail_message_subtype_rel subrel
            ON subrel.mail_followers_id = fol.id
           AND subrel.mail_message_subtype_id = %(subtype_id)s
         WHERE fol.res_model = %(res_model)s
           AND fol.res_id = ANY(%(res_ids)s)
           AND (subrel.mail_followers_id IS NOT NULL
                OR fol.partner_id = ANY(%(pids)s))

         UNION ALL

        SELECT res_partner.id AS pid,
               0 AS res_id,
               FALSE AS is_follower,
               FALSE AS subtype_follower,
               FALSE AS internal
          FROM res_partner
         WHERE res_partner.id = ANY(%(pids)s)
    )
    SELECT {_RECIPIENT_PARTNER_COLUMNS},
           sub_followers.res_id AS res_id,
           sub_followers.is_follower AS is_follower
      FROM res_partner partner
      JOIN sub_followers ON sub_followers.pid = partner.id
                        AND (sub_followers.internal IS NOT TRUE OR partner.partner_share IS NOT TRUE)
{_RECIPIENT_USER_LATERAL}
     WHERE sub_followers.subtype_follower OR partner.id = ANY(%(pids)s)
"""

_RECIPIENT_PARTNERS_QUERY = f"""
    SELECT {_RECIPIENT_PARTNER_COLUMNS},
           ARRAY_AGG(fol.res_id) FILTER (WHERE fol.res_id IS NOT NULL) AS res_ids
      FROM res_partner partner
 LEFT JOIN mail_followers fol ON fol.partner_id = partner.id
                             AND fol.res_model = %(res_model)s
                             AND fol.res_id = ANY(%(res_ids)s)
{_RECIPIENT_USER_LATERAL}
     WHERE partner.id = ANY(%(pids)s)
  GROUP BY partner.id,
           sub_user.uid,
           sub_user.share,
           sub_user.notification_type,
           sub_user.groups
"""

_SUBSCRIPTION_DATA_QUERY = """
    SELECT fol.id,
           fol.res_model,
           fol.res_id,
           fol.partner_id,
           COALESCE(
               ARRAY_AGG(subtype.id ORDER BY subtype.id)
               FILTER (WHERE subtype.id IS NOT NULL), '{}')
           %s
      FROM mail_followers fol
 LEFT JOIN mail_followers_mail_message_subtype_rel fol_rel
        ON fol_rel.mail_followers_id = fol.id
 LEFT JOIN mail_message_subtype subtype ON subtype.id = fol_rel.mail_message_subtype_id
           %s
     WHERE %s
  GROUP BY fol.id %s
"""
_SUBSCRIPTION_PARTNER_COLUMNS = ", partner.partner_share, partner.active"
_SUBSCRIPTION_PARTNER_JOIN = (
    " LEFT JOIN res_partner partner ON partner.id = fol.partner_id"
)
_SUBSCRIPTION_PARTNER_GROUP = ", partner.partner_share, partner.active"
_SUBSCRIPTION_NO_PARTNER_COLUMNS = ", NULL AS partner_share, NULL AS partner_active"


class MailFollowers(models.Model):
    _name = "mail.followers"
    _log_access = False
    _description = "Document Followers"

    res_model = fields.Char("Related Document Model Name", required=True, index=True)
    res_id = fields.Many2oneReference(
        "Related Document ID",
        index=True,
        help="Id of the followed resource",
        model_field="res_model",
    )
    partner_id: ResPartner = fields.Many2one(
        "res.partner",
        string="Related Partner",
        index=True,
        ondelete="cascade",
        required=True,
    )
    subtype_ids: MailMessageSubtype = fields.Many2many(
        "mail.message.subtype",
        string="Subtype",
        help="Message subtypes followed, meaning subtypes that will be pushed onto the user's Wall.",
    )
    is_active = fields.Boolean("Is Active", related="partner_id.active")

    _mail_followers_res_partner_res_model_id_uniq = models.Constraint(
        "unique(res_model,res_id,partner_id)",
        "Error, a partner cannot follow twice the same object.",
    )

    def _invalidate_documents(self, vals_list: list[ValuesType] | None = None) -> None:
        to_invalidate = defaultdict(list)
        for record in vals_list or [
            {"res_model": rec.res_model, "res_id": rec.res_id} for rec in self
        ]:
            if res_id := record.get("res_id"):
                to_invalidate[record.get("res_model")].append(res_id)
        for res_model, res_ids in to_invalidate.items():
            if res_model in self.env:
                self.env[res_model].browse(res_ids).invalidate_recordset()

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        res = super().create(vals_list)
        res._invalidate_documents()
        return res

    def write(self, vals: ValuesType) -> Literal[True]:
        if "res_model" in vals or "res_id" in vals:
            self._invalidate_documents()
        res = super().write(vals)
        if any(fname in vals for fname in ("res_model", "res_id", "partner_id")):
            self._invalidate_documents()
        return res

    def unlink(self) -> Literal[True]:
        documents = [{"res_model": rec.res_model, "res_id": rec.res_id} for rec in self]
        res = super().unlink()
        self._invalidate_documents(documents)
        return res

    @api.depends("partner_id.display_name")
    def _compute_display_name(self) -> None:
        for follower in self:
            follower.display_name = follower.partner_id.sudo().display_name

    @api.model
    def _get_mail_doc_to_followers(self, mail_ids: list[int]) -> dict:
        if not mail_ids:
            return {}
        self.env["mail.mail"].flush_model(["mail_message_id", "recipient_ids"])
        self.env["mail.followers"].flush_model(["partner_id", "res_model", "res_id"])
        self.env["mail.message"].flush_model(["model", "res_id"])
        self.env.cr.execute(
            """
            SELECT message.model, message.res_id, mail_partner.res_partner_id
              FROM mail_mail mail
              JOIN mail_mail_res_partner_rel mail_partner ON mail_partner.mail_mail_id = mail.id
              JOIN mail_message message ON mail.mail_message_id = message.id
              JOIN mail_followers follower ON message.model = follower.res_model
               AND message.res_id = follower.res_id
               AND mail_partner.res_partner_id = follower.partner_id
             WHERE mail.id = ANY(%(mail_ids)s)
        """,
            {"mail_ids": list(mail_ids)},
        )
        res = defaultdict(set)
        for model, doc_id, partner_id in self.env.cr.fetchall():
            res[(model, doc_id)].add(partner_id)
        return dict(res)

    def _get_recipient_data(
        self,
        records: models.BaseModel | None,
        message_type: str,
        subtype_id: int,
        pids: list[int] | None = None,
    ) -> dict:
        self.env["mail.followers"].flush_model(
            ["partner_id", "res_id", "res_model", "subtype_ids"]
        )
        self.env["mail.message.subtype"].flush_model(["internal"])
        self.env["res.users"].flush_model(
            ["active", "group_ids", "notification_type", "partner_id", "share"]
        )
        self.env["res.partner"].flush_model(
            ["active", "email_normalized", "lang", "name", "partner_share"]
        )
        self.env["res.groups"].flush_model(["user_ids"])

        pids = list(pids or [])
        res_ids = records.ids if records else [0]
        params = {
            "subtype_id": subtype_id or 0,
            "res_model": records._name if records else "",
            "res_ids": records.ids if records else [],
            "pids": pids,
        }
        if message_type != "user_notification" and records and subtype_id:
            self.env.cr.execute(_RECIPIENT_FOLLOWERS_QUERY, params)
            res = self.env.cr.fetchall()
        elif pids:
            self.env.cr.execute(_RECIPIENT_PARTNERS_QUERY, params)
            res = []
            for row in self.env.cr.fetchall():
                followed = frozenset(row[-1] or ())
                res += [(*row[:-1], res_id, res_id in followed) for res_id in res_ids]
        else:
            res = []

        doc_infos = {res_id: {} for res_id in res_ids}
        group_closure_cache = {}
        for (
            partner_id,
            is_active,
            email_normalized,
            lang,
            name,
            pshare,
            uid,
            ushare,
            notif,
            groups,
            res_id,
            is_follower,
        ) in res:
            to_update = [res_id] if res_id else res_ids
            group_key = frozenset(groups or ())
            group_ids = group_closure_cache.get(group_key)
            if group_ids is None:
                group_ids = frozenset(
                    self.env["res.groups"].browse(group_key).all_implied_ids.ids
                )
                group_closure_cache[group_key] = group_ids
            if ushare:
                partner_type = "portal"
            elif pshare:
                partner_type = "customer"
            else:
                partner_type = "user"
            for res_id_to_update in to_update:
                if not res_id and partner_id in doc_infos[res_id_to_update]:
                    continue
                doc_infos[res_id_to_update][partner_id] = {
                    "active": is_active,
                    "email_normalized": email_normalized,
                    "groups": group_ids,
                    "id": partner_id,
                    "is_follower": is_follower,
                    "lang": lang,
                    "name": name,
                    "notif": notif,
                    "share": pshare,
                    "type": partner_type,
                    "uid": uid,
                    "ushare": ushare,
                }

        return doc_infos

    def _get_subscription_data(
        self,
        doc_data: list[tuple[str, list[int]]],
        pids: list[int] | None,
        include_partner: bool = False,
    ) -> list:
        if not doc_data:
            return []
        if pids is not None and not pids:
            return []
        self.env["mail.followers"].flush_model(
            ["partner_id", "res_id", "res_model", "subtype_ids"]
        )
        if include_partner:
            self.env["res.partner"].flush_model(["active", "partner_share"])
        where_clause = " OR ".join(
            ["fol.res_model = %s AND fol.res_id = ANY(%s)"] * len(doc_data)
        )
        where_params = list(
            itertools.chain.from_iterable((rm, list(rids)) for rm, rids in doc_data)
        )
        if pids is not None:
            where_clause = "(%s) AND %s" % (where_clause, "fol.partner_id = ANY(%s)")
            where_params.append(list(pids))

        self.env.cr.execute(
            _SUBSCRIPTION_DATA_QUERY
            % (
                _SUBSCRIPTION_PARTNER_COLUMNS
                if include_partner
                else _SUBSCRIPTION_NO_PARTNER_COLUMNS,
                _SUBSCRIPTION_PARTNER_JOIN if include_partner else "",
                where_clause,
                _SUBSCRIPTION_PARTNER_GROUP if include_partner else "",
            ),
            tuple(where_params),
        )
        return self.env.cr.fetchall()

    def _add_followers(
        self,
        res_model: str,
        res_ids: list[int],
        partner_ids: list[int],
        subtypes: dict[int, list[int]] | None = None,
        customer_ids: list[int] | None = None,
        check_existing: bool = True,
        existing_policy: str = "skip",
    ) -> None:
        if not res_ids or not partner_ids:
            return
        if subtypes is None:
            subtypes = self._get_default_subtypes(res_model, partner_ids, customer_ids)
        else:
            wanted = set(partner_ids)
            subtypes = {pid: sids for pid, sids in subtypes.items() if pid in wanted}
        self._add_followers_multi(
            res_model,
            dict.fromkeys(res_ids, subtypes),
            check_existing=check_existing,
            existing_policy=existing_policy,
        )

    def _add_followers_multi(
        self,
        res_model: str,
        subtypes_per_record: dict[int, dict[int, list[int]]],
        check_existing: bool = True,
        existing_policy: str = "skip",
    ) -> None:
        new_vals, updates = self._prepare_followers_vals(
            res_model,
            subtypes_per_record,
            check_existing=check_existing,
            existing_policy=existing_policy,
        )
        sudo_self = self.sudo().with_context(default_partner_id=False)
        if new_vals:
            try:
                with self.env.cr.savepoint(flush=False):
                    sudo_self.create(new_vals).flush_recordset()
            except UniqueViolation:
                self.env["mail.followers"].invalidate_model()
                for vals in new_vals:
                    try:
                        with self.env.cr.savepoint(flush=False):
                            sudo_self.create(vals).flush_recordset()
                    except UniqueViolation:
                        self.env["mail.followers"].invalidate_model()
        by_payload = defaultdict(list)
        for fol_id, (add_sids, remove_sids) in updates.items():
            by_payload[(add_sids, remove_sids)].append(fol_id)
        for (add_sids, remove_sids), fol_ids in by_payload.items():
            sudo_self.browse(fol_ids).write(
                {
                    "subtype_ids": [Command.link(sid) for sid in sorted(add_sids)]
                    + [Command.unlink(sid) for sid in sorted(remove_sids)]
                }
            )

    def _get_default_subtypes(
        self,
        res_model: str,
        partner_ids: list[int],
        customer_ids: list[int] | None = None,
    ) -> dict:
        if not partner_ids:
            return {}

        default, _, external = self.env["mail.message.subtype"].default_subtypes(
            res_model
        )
        if customer_ids is None:
            customer_ids = (
                self.env["res.partner"]
                .sudo()
                .search([("id", "in", partner_ids), ("partner_share", "=", True)])
                .ids
            )
        customer_ids = set(customer_ids)

        return {
            pid: external.ids if pid in customer_ids else default.ids
            for pid in partner_ids
        }

    def _prepare_followers_vals(
        self,
        res_model: str,
        subtypes_per_record: dict[int, dict[int, list[int]]],
        check_existing: bool = False,
        existing_policy: str = "skip",
    ) -> tuple:
        res_ids = list(subtypes_per_record)
        partner_ids = {
            pid for subtypes in subtypes_per_record.values() for pid in subtypes
        }
        existing = {}

        if check_existing and res_ids and partner_ids:
            rows = self._get_subscription_data(
                [(res_model, res_ids)], list(partner_ids)
            )
            if existing_policy == "force":
                self.sudo().browse([row[0] for row in rows]).unlink()
            else:
                existing = {
                    (res_id, partner_id): (fol_id, subtype_ids)
                    for fol_id, _res_model, res_id, partner_id, subtype_ids, _pshare, _active in rows
                }

        new_vals, updates = [], {}
        for res_id, subtypes in subtypes_per_record.items():
            for partner_id, subtype_ids in subtypes.items():
                if (found := existing.get((res_id, partner_id))) is None:
                    new_vals.append(
                        {
                            "res_model": res_model,
                            "res_id": res_id,
                            "partner_id": partner_id,
                            "subtype_ids": [Command.set(sorted(subtype_ids))],
                        }
                    )
                elif existing_policy in ("replace", "update"):
                    fol_id, current_sids = found
                    add_sids = frozenset(subtype_ids) - frozenset(current_sids)
                    remove_sids = (
                        frozenset(current_sids) - frozenset(subtype_ids)
                        if existing_policy == "replace"
                        else frozenset()
                    )
                    if add_sids or remove_sids:
                        updates[fol_id] = (add_sids, remove_sids)

        return new_vals, updates

    def _to_store_defaults(self, target: Store.Target) -> StoreFieldsInput:
        return [
            "display_name",
            "is_active",
            Store.One("partner_id", sudo=True),
            Store.One("thread", [], as_thread=True),
        ]
