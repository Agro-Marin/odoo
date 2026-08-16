import logging
import typing
from collections import defaultdict
from collections.abc import Iterable
from email.message import EmailMessage
from typing import Any, Literal, Self, TypedDict

from lxml import etree
from lxml.builder import E
from markupsafe import Markup

from odoo import _, api, exceptions, fields, models, tools
from odoo.db.schema import column_exists
from odoo.tools import parse_contact_from_email
from odoo.tools.mail import email_normalize, email_split_and_format

from odoo.addons.base.models.ir_model_common import MODULE_UNINSTALL_FLAG
from odoo.addons.mail.tools.alias_error import AliasError

if typing.TYPE_CHECKING:
    from odoo.addons.base.models.res_company import ResCompany
    from odoo.addons.base.models.res_users import ResUsers
    from odoo.addons.mail.models.mail_alias import MailAlias
    from odoo.addons.mail.models.mail_alias_domain import MailAliasDomain
    from odoo.addons.mail.models.mail_message import MailMessage
    from odoo.addons.mail.models.mail_message_subtype import MailMessageSubtype
    from odoo.addons.mail.models.res_partner import ResPartner

_logger = logging.getLogger(__name__)


class RecipientSources(TypedDict):
    email_cc_lst: list[str]
    email_to_lst: list[str]
    partners: ResPartner


class SuggestionSources(TypedDict):
    email_to_lst: list[str]
    partners: ResPartner


class DefaultRecipients(TypedDict):
    email_cc: str
    email_to: str
    partner_ids: list[int]


class SuggestedRecipient(TypedDict, total=False):
    display_name: str
    email: str | Literal[False]
    name: str | Literal[False]
    partner_id: int | Literal[False]
    create_values: dict


_MAIL_EMAIL_FIELD_TYPES = ("char", "text")

_MAIL_TIMEZONE_FIELD_TYPES = ("selection", "char")


def _email_comparison_key(email: str) -> str:
    return email_normalize(email, strict=False) or email.strip()


class Base(models.AbstractModel):
    _inherit = "base"

    _mail_defaults_to_email = False
    _mail_post_access = "write"
    _primary_email = None
    _mail_partner_fields = None
    _mail_default_email_fields = (
        "email_from",
        "x_email_from",
        "email",
        "x_email",
        "partner_email",
        "email_normalized",
    )
    _mail_default_email_cc_fields = ("email_cc", "partner_email_cc", "x_email_cc")

    def _valid_field_parameter(self, field: fields.Field, name: str) -> bool:
        return (
            name == "tracking" and self._abstract
        ) or super()._valid_field_parameter(field, name)

    def with_user(self, user: ResUsers | int) -> Self:
        return super().with_user(user).with_context(guest=None)

    def unlink(self) -> Literal[True]:
        record_ids = self.ids if (not self._abstract and not self._transient) else []
        result = super().unlink()
        if record_ids and (
            not self.env.context.get(MODULE_UNINSTALL_FLAG)
            or (
                column_exists(self.env.cr, "mail_activity", "res_model")
                and column_exists(self.env.cr, "mail_activity", "res_id")
            )
        ):
            self.env["mail.activity"].with_context(active_test=False).sudo().search(
                [("res_model", "=", self._name), ("res_id", "in", record_ids)]
            ).unlink()
        return result

    def _mail_get_operation_for_mail_message_operation(
        self, message_operation: str
    ) -> dict[models.Model, str]:
        valid_operations = {"read", "write", "unlink", "create"}
        if message_operation not in valid_operations:
            raise ValueError(
                "Invalid message operation, should be a valid ORM operation type"
            )
        if self._mail_post_access not in valid_operations:
            raise ValueError(
                "Invalid _mail_post_access, should be a valid ORM operation type"
            )

        if message_operation == "read":
            check_access = "read"
        elif message_operation == "create":
            check_access = self._mail_post_access
        else:
            check_access = "write"
        return dict.fromkeys(self, check_access)

    def _mail_group_by_operation_for_mail_message_operation(
        self, message_operation: str
    ) -> dict[str, models.Model]:
        document_operations = self._mail_get_operation_for_mail_message_operation(
            message_operation
        )
        self_ids = set(self._ids)
        documents = self.browse(
            record.id
            for record, operation in document_operations.items()
            if operation and record.id in self_ids
        ).with_prefetch(self._prefetch_ids)
        return documents.grouped(document_operations.__getitem__)

    def _mail_get_alias_domains(
        self, default_company: ResCompany | Literal[False] = False
    ) -> dict[int, MailAliasDomain]:
        fallback_company = default_company or self.env.company
        record_companies = self._mail_get_companies(default=fallback_company)

        default_domain = fallback_company.alias_domain_id
        all_companies = self.env["res.company"].browse(
            {comp.id for comp in record_companies.values()}
        )
        if not default_domain and any(
            not comp.alias_domain_id for comp in all_companies
        ):
            default_domain = self.env["mail.alias.domain"]._get_default_domain()

        return {
            record.id: (record_companies[record.id].alias_domain_id or default_domain)
            for record in self
        }

    @api.model
    def _mail_get_company_field(self) -> str | Literal[False]:
        field = self._fields.get("company_id")
        if field and field.type == "many2one" and field.comodel_name == "res.company":
            return "company_id"
        return False

    def _mail_get_companies(
        self, default: ResCompany | Literal[False] = False
    ) -> dict[int, ResCompany]:
        default_company = default or self.env["res.company"]
        company_fname = self._mail_get_company_field()
        return {
            record.id: (record[company_fname] or default_company)
            if company_fname
            else default_company
            for record in self
        }

    def _mail_get_customer(self, introspect_fields: bool = False) -> ResPartner:
        self.ensure_one()
        customers = self._mail_get_partners(introspect_fields=introspect_fields)[
            self.id
        ]
        return customers[0] if customers else self.env["res.partner"]

    @api.model
    def _mail_get_partner_fields(self, introspect_fields: bool = False) -> list[str]:
        if self._mail_partner_fields is not None:
            return [
                fname for fname in self._mail_partner_fields if fname in self._fields
            ]
        partner_fnames = [
            fname
            for fname in ("partner_id", "partner_ids")
            if (field := self._fields.get(fname))
            and field.type in ("many2one", "many2many")
            and field.comodel_name == "res.partner"
        ]
        if not partner_fnames and introspect_fields:
            partner_fnames = [
                fname
                for fname, fvalue in self._fields.items()
                if fvalue.type == "many2one" and fvalue.comodel_name == "res.partner"
            ]
        return partner_fnames

    def mail_get_partner_fields(self) -> list[str]:
        return [
            fname
            for fname in self._mail_get_partner_fields()
            if self._fields[fname].type == "many2one"
        ]

    def _mail_get_partners(
        self, introspect_fields: bool = False
    ) -> dict[int, ResPartner]:
        partner_fields = self._mail_get_partner_fields(
            introspect_fields=introspect_fields
        )
        all_pids = {
            pid for record in self for fn in partner_fields for pid in record[fn].ids
        }
        records_partners = {}
        for record in self:
            pids = tools.unique(pid for fn in partner_fields for pid in record[fn].ids)
            records_partners[record.id] = (
                self.env["res.partner"].browse(pids).with_prefetch(all_pids)
            )
        return records_partners

    @api.model
    def _mail_get_primary_email_field(self) -> str | None:
        if not isinstance(self._primary_email, str):
            return None
        field = self._fields.get(self._primary_email)
        if field is not None and field.type in _MAIL_EMAIL_FIELD_TYPES:
            return self._primary_email
        return None

    def _mail_get_primary_email(self) -> dict[int, str | Literal[False]]:
        fname = self._mail_get_primary_email_field()
        return {record.id: record[fname] if fname else False for record in self}

    @api.model
    def mail_allowed_qweb_expressions(self) -> tuple[str, ...]:
        return (
            "object.name",
            "object.contact_name",
            "object.partner_id",
            "object.partner_id.name",
            "object.user_id",
            "object.user_id.name",
            "object.user_id.signature",
        )

    def _mail_track(
        self, tracked_fields: dict, initial_values: dict
    ) -> tuple[set[str], list]:
        self.ensure_one()
        updated = set()
        tracking_value_ids = []

        fields_track_info = self._mail_track_order_fields(tracked_fields)
        for col_name, _sequence in fields_track_info:
            if col_name not in initial_values:
                continue
            initial_value = initial_values[col_name]
            new_value = (
                field.convert_to_read(self[col_name], self)
                if (field := self._fields[col_name]).type == "properties"
                else self[col_name]
            )
            if new_value == initial_value or (not new_value and not initial_value):
                continue

            if self._fields[col_name].type == "properties":
                definition_record_field = self._fields[col_name].definition_record
                if self[definition_record_field] == initial_values.get(
                    definition_record_field, self[definition_record_field]
                ):
                    continue

                updated.add(col_name)
                tracking_value_ids.extend(
                    [
                        0,
                        0,
                        self.env[
                            "mail.tracking.value"
                        ]._create_tracking_values_property(
                            property_,
                            col_name,
                            tracked_fields[col_name],
                            self,
                        ),
                    ]
                    for property_ in initial_value[::-1]
                    if property_["type"] not in ("separator", "html")
                    and property_.get("value")
                )
                continue

            updated.add(col_name)
            tracking_value_ids.append(
                [
                    0,
                    0,
                    self.env["mail.tracking.value"]._create_tracking_values(
                        initial_value,
                        new_value,
                        col_name,
                        tracked_fields[col_name],
                        self,
                    ),
                ]
            )

        return updated, tracking_value_ids

    def _mail_track_order_fields(self, tracked_fields: dict) -> list[tuple[str, int]]:
        fields_track_info = [
            (col_name, self._mail_track_get_field_sequence(col_name))
            for col_name in tracked_fields
        ]
        fields_track_info.sort(
            key=lambda item: (
                item[1],
                tracked_fields[item[0]]["type"] != "properties",
                item[0],
            ),
            reverse=True,
        )
        return fields_track_info

    def _mail_track_get_field_sequence(self, fname: str) -> int:
        if fname not in self._fields:
            return 100

        def get_field_sequence(fname: str) -> int:
            return getattr(self._fields[fname], "tracking", True)

        sequence = get_field_sequence(fname)
        if self._fields[fname].type == "properties" and sequence is True:
            parent_sequence = get_field_sequence(self._fields[fname].definition_record)
            return 100 if parent_sequence is True else parent_sequence
        return 100 if sequence is True else sequence

    def _message_get_default_recipients_sources(self) -> dict[int, RecipientSources]:
        res = {}
        customers = self._mail_get_partners()
        primary_emails = self._mail_get_primary_email()
        for record in self:
            email_cc_lst, email_to_lst = [], []
            recipients_all = customers[record.id]
            email_to = primary_emails[record.id] or record._mail_find_email_value(
                self._mail_default_email_fields
            )
            if email_to:
                email_to_lst = tools.mail.email_split_and_format_normalize(
                    email_to
                ) or [email_to]
            email_cc = record._mail_find_email_value(self._mail_default_email_cc_fields)
            if email_cc:
                email_cc_lst = tools.mail.email_split_and_format_normalize(
                    email_cc
                ) or [email_cc]

            res[record.id] = {
                "email_cc_lst": email_cc_lst,
                "email_to_lst": email_to_lst,
                "partners": recipients_all,
            }
        return res

    def _mail_find_email_value(self, fnames: Iterable[str]) -> str | Literal[False]:
        self.ensure_one()
        return next(
            (
                self[fname]
                for fname in fnames
                if (field := self._fields.get(fname))
                and field.type in _MAIL_EMAIL_FIELD_TYPES
                and self[fname]
            ),
            False,
        )

    def _mail_get_banned_emails(self, emails: Iterable[str]) -> set:
        root_email = self.env.ref("base.partner_root").email_normalized
        banned = {root_email} if root_email else set()
        banned.update(
            alias
            for alias in self.env["mail.alias.domain"]
            .sudo()
            ._find_aliases(
                [_email_comparison_key(e) for e in emails if e and e.strip()]
            )
            if alias
        )
        return banned

    def _message_get_default_recipients(
        self, with_cc: bool = False
    ) -> dict[int, DefaultRecipients]:
        res = {}
        prioritize_email = self._mail_defaults_to_email
        found = self._message_get_default_recipients_sources()

        all_emails = []
        for defaults in found.values():
            all_emails += defaults["email_to_lst"]
            if with_cc:
                all_emails += defaults["email_cc_lst"]
            all_emails += defaults["partners"].mapped("email_normalized")
        ban_emails = self._mail_get_banned_emails(all_emails)

        for record in self:
            defaults = found[record.id]
            customers = defaults["partners"]
            email_cc_lst = defaults["email_cc_lst"] if with_cc else []
            email_to_lst = defaults["email_to_lst"]

            recipients_all = customers.filtered(
                lambda p: (
                    not p.is_public
                    and (not p.email_normalized or p.email_normalized not in ban_emails)
                )
            )
            recipients = customers.filtered(
                lambda p: (
                    not p.is_public
                    and p.email_normalized
                    and p.email_normalized not in ban_emails
                )
            )
            email_cc_lst = [
                e for e in email_cc_lst if _email_comparison_key(e) not in ban_emails
            ]
            email_to_lst = [
                e for e in email_to_lst if _email_comparison_key(e) not in ban_emails
            ]

            if not prioritize_email or not email_to_lst:
                if recipients:
                    partner_ids = recipients.ids
                    email_to = ""
                elif (
                    recipients_all
                    and len(recipients_all) == len(email_to_lst)
                    and all(
                        email in recipients_all.mapped("email")
                        for email in email_to_lst
                    )
                ):
                    partner_ids = recipients_all.ids
                    email_to = ""
                else:
                    partner_ids = [] if email_to_lst else recipients_all.ids
                    email_to = ",".join(email_to_lst)
            elif len(email_to_lst) == len(recipients) and all(
                tools.email_normalize(email) in recipients.mapped("email_normalized")
                for email in email_to_lst
            ):
                partner_ids = recipients.ids
                email_to = ""
            else:
                partner_ids = []
                email_to = ",".join(email_to_lst)
            res[record.id] = {
                "email_cc": ",".join(email_cc_lst),
                "email_to": email_to,
                "partner_ids": partner_ids,
            }
        return res

    def _message_get_suggested_recipients_sources(
        self, force_primary_email: str | Literal[False] = False
    ) -> dict[int, SuggestionSources]:
        suggested = {
            record.id: {"email_to_lst": [], "partners": self.env["res.partner"]}
            for record in self
        }
        defaults = self._message_get_default_recipients_sources()

        user_field = self._fields.get("user_id")
        if (
            user_field
            and user_field.type == "many2one"
            and user_field.comodel_name == "res.users"
        ):
            for record_su in self.sudo():
                if record_su.user_id.partner_id == self.env.user.partner_id:
                    continue
                suggested[record_su.id]["partners"] += record_su.user_id.partner_id

        for record_id, values in defaults.items():
            suggested[record_id]["partners"] |= values["partners"]

        for record in self:
            if force_primary_email:
                suggested[record.id]["email_to_lst"] += (
                    tools.mail.email_split_and_format_normalize(force_primary_email)
                )
            else:
                suggested[record.id]["email_to_lst"] += defaults[record.id][
                    "email_to_lst"
                ]

        return suggested

    def _message_get_suggested_recipients_batch(
        self,
        reply_discussion: bool = False,
        reply_message: MailMessage | None = None,
        no_create: bool = True,
        primary_email: str | Literal[False] = False,
        additional_partners: ResPartner | None = None,
    ) -> dict[int, list[SuggestedRecipient]]:

        is_mail_thread = self.env["mail.thread"]._mail_is_thread(self)
        suggested_record = self._message_get_suggested_recipients_sources(
            force_primary_email=primary_email
        )

        suggested = {
            record.id: {
                "email_to_lst": suggested_record[record.id]["email_to_lst"].copy(),
                "partners": suggested_record[record.id]["partners"]
                + (additional_partners or self.env["res.partner"]),
            }
            for record in self
        }
        self._message_add_suggested_recipients_from_replies(
            suggested, reply_discussion=reply_discussion, reply_message=reply_message
        )

        followers_by_record = {
            record.id: record.sudo().message_partner_ids
            if is_mail_thread
            else self.env["res.partner"]
            for record in self
        }
        follower_ids = {
            pid for recs in followers_by_record.values() for pid in recs._ids
        }
        followers_by_record = {
            res_id: recs.with_prefetch(follower_ids)
            for res_id, recs in followers_by_record.items()
        }
        customer_ids = {
            pid for vals in suggested.values() for pid in vals["partners"]._ids
        }
        suggested = {
            res_id: {**vals, "partners": vals["partners"].with_prefetch(customer_ids)}
            for res_id, vals in suggested.items()
        }

        records_emails = {}
        all_emails = set()
        for record in self:
            partners = suggested[record.id]["partners"]
            followers = followers_by_record[record.id]
            skip_emails = (
                set(followers.mapped("email_normalized"))
                | set(followers.mapped("email"))
                | set(partners.mapped("email_normalized"))
                | set(partners.mapped("email"))
            )
            records_emails[record] = [
                e
                for email_input in suggested[record.id]["email_to_lst"]
                for e in email_split_and_format(email_input)
                if e and e.strip() and _email_comparison_key(e) not in skip_emails
            ]
            all_emails |= set(records_emails[record]) | set(
                partners.mapped("email_normalized")
            )
        ban_emails = self._mail_get_banned_emails(all_emails)

        additional_values = (
            None
            if is_mail_thread
            else self._message_suggested_recipients_company_values(records_emails)
        )
        thread_recs = self if is_mail_thread else self.env["mail.thread"]
        records_partners = thread_recs._partner_find_from_emails(
            records_emails,
            avoid_alias=False,
            ban_emails=list(ban_emails),
            no_create=no_create,
            additional_values=additional_values,
        )

        customer_ids |= {pid for recs in records_partners.values() for pid in recs._ids}

        suggested_recipients = {}
        for record in self:
            emails_normalized_info = (
                record._get_customer_information() if is_mail_thread else {}
            )
            followers = followers_by_record[record.id]
            partners = (
                self.env["res.partner"]
                .browse(
                    tools.misc.unique(
                        p.id
                        for p in (
                            suggested[record.id]["partners"]
                            + records_partners[record.id]
                        ).with_prefetch(customer_ids)
                        if (
                            (
                                p not in followers
                                or (
                                    p in suggested_record[record.id]["partners"]
                                    and p.partner_share
                                )
                            )
                            and p.email_normalized not in ban_emails
                            and not p.is_public
                        )
                    )
                )
                .with_prefetch(customer_ids)
            )
            existing_mails = {
                _email_comparison_key(e)
                for rec in (followers | partners)
                for e in ([rec.email_normalized] if rec.email_normalized else [])
                + email_split_and_format(rec.email or "")
            }
            suggested_recipients[record.id] = self._message_suggested_recipients_values(
                partners,
                self._message_suggested_emails(
                    suggested[record.id]["email_to_lst"],
                    skip_keys=ban_emails | existing_mails,
                ),
                emails_normalized_info,
            )
        return suggested_recipients

    def _message_add_suggested_recipients_from_replies(
        self,
        suggested: dict,
        reply_discussion: bool = False,
        reply_message: MailMessage | None = None,
    ) -> None:
        sorted_messages = {}
        if reply_discussion and self.env["mail.thread"]._mail_is_thread(self):
            messages_by_res_id = self.message_ids.grouped("res_id")
            sorted_messages = {
                record.id: record._sort_suggested_messages(
                    messages_by_res_id.get(record.id, self.env["mail.message"])
                )
                for record in self
            }
        if not reply_message and not any(sorted_messages.values()):
            return
        for record in self:
            record_msg = reply_message or next(
                iter(sorted_messages.get(record.id, self.env["mail.message"])),
                self.env["mail.message"],
            )
            if not record_msg:
                continue
            suggested[record.id]["partners"] += (
                record_msg.partner_ids | record_msg.author_id
            ).filtered(lambda p: p.active)
            suggested[record.id]["email_to_lst"] += [
                record_msg.incoming_email_to or "",
                record_msg.incoming_email_cc or "",
                record_msg.email_from or "",
            ]

    def _message_suggested_recipients_company_values(
        self, records_emails: dict[models.BaseModel, list[str]]
    ) -> dict[str, dict]:
        record_companies = self._mail_get_companies()
        values = {}
        for record, emails in records_emails.items():
            company = record_companies.get(record.id)
            if not company:
                continue
            for email in emails:
                values.setdefault(_email_comparison_key(email), {}).setdefault(
                    "company_id", company.id
                )
        return values

    def _message_suggested_emails(
        self, email_to_lst: list[str], skip_keys: set[str]
    ) -> list[str]:
        by_key = {}
        for email_input in email_to_lst:
            for email in email_split_and_format(email_input):
                if not (email and email.strip()):
                    continue
                key = _email_comparison_key(email)
                if key in skip_keys:
                    continue
                current = by_key.get(key)
                if current is None or (
                    not parse_contact_from_email(current)[0]
                    and parse_contact_from_email(email)[0]
                ):
                    by_key[key] = email
        return list(by_key.values())

    def _message_suggested_recipients_values(
        self,
        partners: ResPartner,
        email_to_lst: list[str],
        emails_normalized_info: dict,
    ) -> list[SuggestedRecipient]:
        recipients = [
            {
                **({"display_name": partner.display_name} if not partner.name else {}),
                "email": partner.email_normalized,
                "name": partner.name,
                "partner_id": partner.id,
                "create_values": {},
            }
            for partner in partners
        ]
        for email_input in email_to_lst:
            name, email_normalized = parse_contact_from_email(email_input)
            create_values = dict(emails_normalized_info.get(email_normalized, {}))
            recipients.append(
                {
                    "email": email_normalized,
                    "name": create_values.pop("name", False) or name,
                    "partner_id": False,
                    "create_values": create_values,
                }
            )
        return recipients

    def _sort_suggested_messages(self, messages: MailMessage) -> MailMessage:
        subtype_ids = (
            self._creation_subtype().ids
            if self.env["mail.thread"]._mail_is_thread(self)
            else []
        )
        subtype_ids.append(
            self.env["ir.model.data"]._xmlid_to_res_id("mail.mt_comment")
        )
        return messages.filtered(
            lambda msg: (
                msg.message_type in ("email", "comment")
                and msg.subtype_id.id in subtype_ids
            )
        ).sorted(lambda msg: (msg.date, msg.id), reverse=True)

    def _message_get_suggested_recipients(
        self,
        reply_discussion: bool = False,
        reply_message: MailMessage | None = None,
        no_create: bool = True,
        primary_email: str | Literal[False] = False,
        additional_partners: ResPartner | None = None,
    ) -> list[SuggestedRecipient]:
        self.ensure_one()
        return self._message_get_suggested_recipients_batch(
            reply_discussion=reply_discussion,
            reply_message=reply_message,
            no_create=no_create,
            primary_email=primary_email,
            additional_partners=additional_partners,
        )[self.id]

    def _notify_get_reply_to(
        self,
        default: str | Literal[False] | None = None,
        author_id: int | Literal[False] = False,
    ) -> dict[int | Literal[False], str | Literal[False]]:
        return self._notify_get_reply_to_batch(
            defaults=dict.fromkeys(self.ids or [False], default),
            author_ids=dict.fromkeys(self.ids or [False], author_id),
        )

    def _notify_get_reply_to_addresses(
        self,
    ) -> dict[int | Literal[False], str]:
        model = self._name if self and self._name != "mail.thread" else False
        res_ids = self.ids if model else []
        _res_ids = res_ids or [False]

        if res_ids:
            company_to_res_ids = defaultdict(list)
            for record_id, company in (
                self.sudo()._mail_get_companies(default=self.env.company).items()
            ):
                company_to_res_ids[company].append(record_id)
        else:
            company_to_res_ids = {self.env.company: _res_ids}

        reply_to_email = {}
        if model and res_ids:
            mail_aliases = (
                self.env["mail.alias"]
                .sudo()
                .search(
                    [
                        ("alias_domain_id", "!=", False),
                        ("alias_parent_model_id.model", "=", model),
                        ("alias_parent_thread_id", "in", res_ids),
                        ("alias_name", "!=", False),
                    ]
                )
            )
            for alias in mail_aliases:
                reply_to_email.setdefault(
                    alias.alias_parent_thread_id, alias.alias_full_name
                )

        if set(_res_ids) - set(reply_to_email):
            for company, record_ids in company_to_res_ids.items():
                if not company.catchall_email:
                    continue
                left_ids = set(record_ids) - set(reply_to_email)
                if left_ids:
                    reply_to_email.update(
                        dict.fromkeys(left_ids, company.catchall_email)
                    )
        return reply_to_email

    def _notify_get_reply_to_batch(
        self, defaults: dict | None = None, author_ids: dict | None = None
    ) -> dict[int | Literal[False], str | Literal[False]]:
        model = self._name if self and self._name != "mail.thread" else False
        res_ids = self.ids if model else []
        _res_ids = res_ids or [False]
        if defaults is None:
            defaults = dict.fromkeys(_res_ids, False)
        if author_ids is None:
            author_ids = dict.fromkeys(_res_ids, False)

        if set(defaults.keys()) != set(_res_ids):
            raise ValueError(
                f"Invalid defaults, keys {defaults.keys()} does not match recordset IDs {_res_ids}"
            )
        if set(author_ids.keys()) != set(_res_ids):
            raise ValueError(
                f"Invalid author_ids, keys {author_ids.keys()} does not match recordset IDs {_res_ids}"
            )

        reply_to_email = self._notify_get_reply_to_addresses()

        self.env["res.partner"].browse(
            {author_ids[res_id] for res_id in reply_to_email if author_ids.get(res_id)}
        ).mapped("name")
        reply_to_formatted = dict(defaults)
        for res_id, record_reply_to in reply_to_email.items():
            reply_to_formatted[res_id] = self._notify_get_reply_to_formatted_email(
                record_reply_to,
                author_id=author_ids[res_id],
            )

        return reply_to_formatted

    def _notify_get_reply_to_formatted_email(
        self, record_email: str, author_id: int | Literal[False] = False
    ) -> str:
        length_limit = 68
        if len(record_email) >= length_limit:
            _logger.warning(
                "Notification email address for reply-to is longer than 68 characters. "
                "This might create non-compliant folding in the email header in certain DKIM "
                "verification tech stacks. It is advised to shorten it if possible. "
                "Reply-To: %s ",
                record_email,
            )
            return record_email

        if author_id:
            author_name = self.env["res.partner"].browse(author_id).name
        else:
            author_name = self.env.user.name

        formatted_email = tools.formataddr((author_name, record_email))
        if len(formatted_email) > length_limit:
            formatted_email = tools.formataddr((self.env.user.name, record_email))
        if len(formatted_email) > length_limit:
            formatted_email = record_email
        return formatted_email

    def _alias_get_error(
        self, message: EmailMessage, message_dict: dict, alias: MailAlias
    ) -> AliasError | Literal[False]:
        author = self.env["res.partner"].browse(message_dict.get("author_id", False))
        if alias.alias_contact == "followers":
            if not self.ids:
                return AliasError(
                    "config_follower_no_record",
                    _("incorrectly configured alias (unknown reference record)"),
                    is_config_error=True,
                )
            if "message_partner_ids" not in self._fields:
                return AliasError(
                    "config_follower_no_partners",
                    _("incorrectly configured alias"),
                    is_config_error=True,
                )
            if not author or author not in self.message_partner_ids:
                return AliasError(
                    "error_follower_not_following", _("restricted to followers")
                )
        elif alias.alias_contact == "partners" and not author:
            return AliasError(
                "error_partners_no_partner", _("restricted to known authors")
            )
        return False

    @api.model
    def _get_default_activity_view(self) -> etree._Element:
        field = E.field(name=self._rec_name_fallback())
        activity_box = E.div(field, {"t-name": "activity-box"})
        templates = E.templates(activity_box)
        return E.activity(templates, string=self._description)

    def _mail_get_message_subtypes(self) -> MailMessageSubtype:
        return self.env["mail.message.subtype"].search(
            [
                "&",
                ("hidden", "=", False),
                "|",
                ("res_model", "=", self._name),
                ("res_model", "=", False),
            ]
        )

    def _notify_by_email_get_headers(
        self, headers: dict[str, str] | None = None
    ) -> dict[str, str]:
        headers = dict(headers or {})
        if not self:
            return headers
        self.ensure_one()
        headers.setdefault("X-Odoo-Objects", f"{self._name}-{self.id}")
        if "Return-Path" not in headers:
            company = self._mail_get_companies(default=self.env.company)[self.id]
            if company.bounce_email:
                headers["Return-Path"] = company.bounce_email
        return headers

    def _get_html_link(self, title: str | None = None) -> Markup:
        self.ensure_one()
        return Markup("<a href=# data-oe-model='%s' data-oe-id='%s'>%s</a>") % (
            self._name,
            self.id,
            title or self.display_name,
        )

    @api.model
    def _get_backend_root_menu_ids(self) -> list[int]:
        return []

    def _find_value_from_field_path(self, field_path: str) -> str:
        if self:
            self.ensure_one()

        if not field_path:
            return ""

        try:
            field_value = self.mapped(field_path)
        except KeyError as err:
            raise exceptions.UserError(
                _(
                    "%(model_name)s.%(field_path)s does not seem to be a valid field path",
                    model_name=self._name,
                    field_path=field_path,
                )
            ) from err
        except Exception as err:
            _logger.warning(
                "Could not read field path %s.%s", self._name, field_path, exc_info=True
            )
            raise exceptions.UserError(
                _(
                    "We were not able to fetch value of field '%(field)s'",
                    field=field_path,
                )
            ) from err
        if isinstance(field_value, models.Model):
            return " ".join((value.display_name or "") for value in field_value)

        field_path_models = field_path.rsplit(".", 1)
        if len(field_path_models) > 1:
            last_model_path, last_fname = field_path_models
            last_model = self.mapped(last_model_path)
        else:
            last_model, last_fname = self, field_path
        last_field = last_model._fields[last_fname]
        keep_falsy = last_field.type == "boolean"
        return " ".join(
            self._mail_format_field_value(value, last_field, record)
            for record, value in ((rec, rec[last_fname]) for rec in last_model)
            if keep_falsy or (value is not False and value is not None and value != "")
        )

    def _mail_format_field_value(
        self, value: Any, field: fields.Field, record: models.Model
    ) -> str:
        if field.type == "selection":
            return field.convert_to_export(value, record) or ""
        if field.type == "datetime":
            tz = (self and self._mail_get_timezone()) or self.env.user.tz or "UTC"
            return f"{tools.format_datetime(self.env, value, tz=tz)} {tz}"
        if field.type == "date":
            return tools.format_date(self.env, value)
        if field.type == "monetary":
            currency_fname = field.get_currency_field(record)
            currency = record[currency_fname] if record and currency_fname else None
            return tools.formatLang(self.env, value, currency_obj=currency or None)
        if field.type == "float":
            digits = field.get_digits(self.env)
            return tools.formatLang(self.env, value, digits=digits[1] if digits else 2)
        if field.type == "boolean":
            return _("Yes") if value else _("No")
        return str(value)

    def _mail_get_timezone(self) -> str | None:
        self.ensure_one()
        return next(
            (
                self[tz_field]
                for tz_field in ("date_tz", "tz", "timezone")
                if (field := self._fields.get(tz_field))
                and field.type in _MAIL_TIMEZONE_FIELD_TYPES
                and self[tz_field]
            ),
            None,
        )
