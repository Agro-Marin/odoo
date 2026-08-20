import typing
from collections import defaultdict
from typing import Literal

from odoo import models, modules, tools
from odoo.exceptions import MissingError
from odoo.fields import Domain
from odoo.tools import groupby
from odoo.tools.misc import OrderedSet

from odoo.addons.mail.tools.discuss import Store, StoreFieldsInput, StoreFieldSpec

if typing.TYPE_CHECKING:
    from .mail_followers import MailFollowers


class MailMessage(models.Model):
    _inherit = "mail.message"

    def _field_store_repr(self, field_spec: StoreFieldSpec) -> list[StoreFieldSpec]:
        if field_spec == "message_link_preview_ids":
            return [
                Store.Many(
                    "message_link_preview_ids",
                    value=lambda m: (
                        m.sudo()
                        .message_link_preview_ids.filtered(
                            lambda message_link_preview: (
                                not message_link_preview.is_hidden
                            )
                        )
                        .sorted(
                            lambda message_link_preview: (
                                message_link_preview.sequence,
                                message_link_preview.id,
                            )
                        )
                    ),
                )
            ]
        return [field_spec]

    def _is_envelope_visible(self, target: Store.Target) -> bool:
        self.ensure_one()
        return target.is_internal(self.env) or not (
            self.author_id or self.author_guest_id
        )

    def _to_store_defaults(self, target: Store.Target) -> StoreFieldsInput:
        field_names = [
            Store.Many(
                "attachment_ids",
                sort="id",
                dynamic_fields=lambda m: m._get_store_attachment_fields(target),
                sudo=True,
            ),
            Store.One("author_guest_id", ["avatar_128", "name"], sudo=True),
            Store.One(
                "author_id",
                [
                    "avatar_128",
                    "is_company",
                    Store.One("main_user_id", ["partner_id", "share"]),
                ],
                dynamic_fields=lambda m: m._get_store_partner_name_fields(),
                sudo=True,
            ),
            "body",
            "create_date",
            "date",
            Store.Attr(
                "email_from", predicate=lambda m: m._is_envelope_visible(target)
            ),
            Store.Attr(
                "incoming_email_cc", predicate=lambda m: m._is_envelope_visible(target)
            ),
            Store.Attr(
                "incoming_email_to", predicate=lambda m: m._is_envelope_visible(target)
            ),
            "message_format",
            "message_link_preview_ids",
            "message_type",
            "model",
            Store.Many(
                "partner_ids",
                "avatar_128",
                dynamic_fields=lambda m: m._get_store_partner_name_fields(),
                sort="id",
                sudo=True,
            ),
            "pinned_at",
            Store.Attr("reactions", value=lambda m: Store.Many(m.sudo().reaction_ids)),
            "record_name",
            "res_id",
            "subject",
            Store.One("subtype_id", ["description"], sudo=True),
            "write_date",
            *self._get_store_linked_messages_fields(),
        ]
        if target.is_internal(self.env) and not self.env.context.get(
            "mail_notify_inbox"
        ):
            field_names.append(
                Store.Many(
                    "notification_ids",
                    value=lambda m: (
                        m.sudo().notification_ids._filtered_for_web_client()
                    ),
                ),
            )
        return field_names

    def _to_store(
        self,
        store: Store,
        fields: list[StoreFieldSpec],
        *,
        format_reply: bool = True,
        msg_vals: dict | Literal[False] = False,
        add_followers: bool = False,
        followers: MailFollowers | None = None,
    ) -> None:
        fields = list(fields)
        if "message_format" not in fields:
            store.add_records_fields(self, fields)
            return
        fields.remove("message_format")
        scheduled_dt_by_msg_id = self._store_scheduled_datetimes(msg_vals)
        record_by_message = self._record_by_message()
        records = list(
            {(r._name, r.id): r for r in record_by_message.values()}.values()
        )
        record_fields = self._store_thread_fields(
            store, records, add_followers=add_followers, followers=followers
        )
        for record in records:
            store.add(record, record_fields, as_thread=True)
        if store.target.is_current_user(self.env):
            fields.append("starred")
        store.add(self, fields)
        for message in self:
            store.add(
                message,
                message._store_message_extras(
                    store,
                    record_by_message.get(message),
                    scheduled_dt_by_msg_id.get(message.id, False),
                ),
            )
        self._extras_to_store(store, format_reply=format_reply)

    def _store_scheduled_datetimes(self, msg_vals: dict | Literal[False]) -> dict:
        if msg_vals:
            self.ensure_one()
            return {self.id: msg_vals.get("scheduled_date", False)}
        if not self:
            return {}
        schedulers = (
            self.env["mail.message.schedule"]
            .sudo()
            .search_fetch(
                [("mail_message_id", "in", self.ids)],
                ["mail_message_id", "scheduled_datetime"],
            )
        )
        return {
            scheduler.mail_message_id.id: scheduler.scheduled_datetime
            for scheduler in schedulers
        }

    def _store_thread_fields(
        self,
        store: Store,
        records: list,
        *,
        add_followers: bool = False,
        followers: MailFollowers | None = None,
    ) -> list[StoreFieldSpec]:
        record_fields = [
            Store.Attr("display_name", sudo=True),
            Store.Attr(
                "has_mail_thread",
                lambda record: isinstance(record, self.pool["mixin.mail.thread"]),
            ),
            Store.Attr(
                "module_icon",
                lambda record: modules.module.get_module_icon(
                    self.env[record._name]._original_module
                ),
                predicate=lambda record: self.env[record._name]._original_module,
            ),
        ]
        non_channel_records = sorted(
            (record for record in records if record._name != "discuss.channel"),
            key=lambda record: record._name,
        )
        target_user = store.target.get_user(self.env)
        if not (target_user and add_followers and non_channel_records):
            return record_fields
        if followers is None:
            domain = Domain.OR(
                [
                    ("res_model", "=", model),
                    ("res_id", "in", [r.id for r in model_records]),
                ]
                for model, model_records in groupby(
                    non_channel_records, key=lambda r: r._name
                )
            )
            domain &= Domain("partner_id", "=", target_user.partner_id.id)
            followers = (
                self.env["mail.followers"]
                .sudo()
                .search_fetch(domain, ["res_model", "res_id", "partner_id"])
            )
        follower_by_record_and_partner = {
            (
                self.env[follower.res_model].browse(follower.res_id),
                follower.partner_id,
            ): follower
            for follower in followers
            if follower.res_model in self.env
        }
        record_fields.append(
            Store.One(
                "selfFollower",
                ["is_active", Store.One("partner_id", [])],
                value=lambda r: follower_by_record_and_partner.get(
                    (r, target_user.partner_id)
                ),
            ),
        )
        return record_fields

    def _store_message_extras(self, store: Store, record, scheduled_datetime) -> dict:
        self.ensure_one()
        if record:
            try:
                if isinstance(record, self.pool["mixin.mail.thread"]):
                    default_subject = record.sudo()._message_compute_subject()
                else:
                    default_subject = self.record_name
            except MissingError:
                record = None
                default_subject = False
        else:
            default_subject = False
        data = {
            "default_subject": default_subject,
            "scheduledDatetime": scheduled_datetime,
            "thread": Store.One(record, [], as_thread=True),
        }
        envelope_visible = self._is_envelope_visible(store.target)
        if envelope_visible and self.incoming_email_cc:
            data["incoming_email_cc"] = tools.mail.email_split_tuples(
                self.incoming_email_cc
            )
        if envelope_visible and self.incoming_email_to:
            data["incoming_email_to"] = tools.mail.email_split_tuples(
                self.incoming_email_to
            )
        if store.target.is_current_user(self.env):
            displayed_tracking_ids = (
                self.sudo().tracking_value_ids._filter_has_field_access(self.env)
            )
            if record and isinstance(record, self.pool["mixin.mail.thread"]):
                displayed_tracking_ids = record._track_filter_for_display(
                    displayed_tracking_ids
                )
            notifications_partners = (
                self.sudo()
                .notification_ids.filtered(lambda n: not n.is_read)
                .res_partner_id
            )
            data["needaction"] = (
                not self.env.user._is_public()
                and self.env.user.partner_id in notifications_partners
            )
            data["trackingValues"] = displayed_tracking_ids._tracking_value_format()
        return data

    def _get_store_partner_name_fields(self) -> list[StoreFieldSpec]:
        self.ensure_one()
        return ["name"]

    def _get_store_attachment_fields(
        self, target: Store.Target
    ) -> list[StoreFieldSpec]:
        self.ensure_one()
        if target.is_current_user(self.env) and self.is_current_user_or_guest_author:
            return self.env["ir.attachment"]._get_store_ownership_fields()
        return []

    def _get_store_linked_messages_fields(self) -> list[StoreFieldSpec]:
        by_message, linked_messages = self._get_linked_messages()
        record_by_message = linked_messages._record_by_message()
        return [
            Store.Many(
                "linked_message_ids",
                [
                    "model",
                    "res_id",
                    Store.Attr(
                        "thread",
                        lambda m: Store.One(
                            record_by_message.get(m),
                            [Store.Attr("display_name", sudo=True)],
                            as_thread=True,
                        ),
                    ),
                ],
                value=lambda m: by_message.get(m.id, m.browse()),
                only_data=True,
            ),
        ]

    def _extras_to_store(self, store: Store, format_reply: bool) -> None:
        pass

    def _message_notifications_to_store(self, store: Store) -> None:
        store.add(
            self,
            [
                Store.One("author_id", []),
                Store.One("author_guest_id", []),
                "body",
                "date",
                "message_type",
                Store.Many(
                    "notification_ids",
                    value=lambda m: m.notification_ids._filtered_for_web_client(),
                ),
                Store.One(
                    "thread",
                    [
                        Store.Attr(
                            "modelName",
                            lambda thread: (
                                self.env["ir.model"]._get(thread._name).display_name
                            ),
                        ),
                        Store.Attr("display_name", sudo=True),
                    ],
                    as_thread=True,
                ),
            ],
        )

    def _notify_message_notification_update(self) -> None:
        record_by_message = self._record_by_message()
        ids_by_model = defaultdict(list)
        for record in record_by_message.values():
            ids_by_model[record._name].append(record.id)
        accessible_ids_by_model = {
            model: set(
                self.env[model].browse(ids).exists()._filtered_access("read")._ids
            )
            for model, ids in ids_by_model.items()
        }
        message_ids_by_partner = defaultdict(OrderedSet)
        for message in self:
            record = record_by_message.get(message)
            if not record or record.id not in accessible_ids_by_model.get(
                record._name, ()
            ):
                continue
            if not self.env.user._is_public():
                message_ids_by_partner[self.env.user.partner_id].add(message.id)
            if message.author_id and not any(
                user._is_public()
                for user in message.author_id.with_context(active_test=False).user_ids
            ):
                message_ids_by_partner[message.author_id].add(message.id)
        for partner, message_ids in message_ids_by_partner.items():
            if user := partner.main_user_id:
                store = Store(bus_channel=user)
                self.browse(message_ids).with_user(
                    user
                )._message_notifications_to_store(store)
                store.bus_send()
