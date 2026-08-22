import base64
import typing
from collections import defaultdict
from copy import deepcopy
from datetime import timedelta
from hashlib import sha512
from secrets import token_urlsafe
from types import NotImplementedType
from typing import Any, Literal, NoReturn, Self

from markupsafe import Markup

from odoo import Command, api, fields, models, tools
from odoo.api import ValuesType
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain
from odoo.libs.colors import hsl_from_seed
from odoo.libs.sql import SQL
from odoo.tools import email_normalize, format_list, html_escape
from odoo.tools.misc import OrderedSet, hash_sign

from odoo.addons.base.models.ir_mail_server import MailDeliveryException
from odoo.addons.mail.models.discuss.discuss_channel_member import AVATAR_CARD_FIELDS
from odoo.addons.mail.tools.channel_avatar import CHANNEL_AVATAR, GROUP_AVATAR
from odoo.addons.mail.tools.discuss import Store, StoreFieldsInput, StoreFieldSpec
from odoo.addons.mail.tools.recipients import build_recipient_data
from odoo.addons.mail.tools.web_push import PUSH_NOTIFICATION_TYPE

if typing.TYPE_CHECKING:
    from ..mail_message import MailMessage
    from ..res_partner import ResPartner
    from .discuss_call_history import DiscussCallHistory
    from .discuss_channel_member import DiscussChannelMember
    from .discuss_channel_rtc_session import DiscussChannelRtcSession
    from .mail_guest import MailGuest
    from odoo.addons.base.models.res_users import ResUsers
    from odoo.addons.bus.models.ir_attachment import IrAttachment
    from odoo.addons.bus.models.res_groups import ResGroups


def is_channel(channel: DiscussChannel) -> bool:
    return channel.channel_type == "channel"


def is_channel_or_group(channel: DiscussChannel) -> bool:
    return channel.channel_type in ("channel", "group")


class DiscussChannel(models.Model):
    _name = "discuss.channel"
    _description = "Discussion Channel"
    _mail_flat_thread = False
    _mail_post_access = "read"
    _inherit = ["mixin.mail.thread", "mixin.store.sync"]

    MAX_BOUNCE_LIMIT = 10

    MAX_EMAIL_INVITES = 100

    _STRUCTURAL_WRITE_FIELDS = frozenset(
        {
            "name",
            "description",
            "image_128",
            "group_public_id",
            "group_ids",
            "active",
            "uuid",
            "default_display_mode",
            "channel_type",
        }
    )

    name = fields.Char("Name", required=True)

    active = fields.Boolean(
        default=True,
        help="Set active to false to hide the channel without removing it.",
    )

    channel_type = fields.Selection(
        [("chat", "Chat"), ("channel", "Channel"), ("group", "Group")],
        string="Channel Type",
        required=True,
        default="channel",
        readonly=True,
        help="Chat is private and unique between 2 persons. Group is private among invited persons. Channel can be freely joined (depending on its configuration).",
    )

    is_editable = fields.Boolean("Is Editable", compute="_compute_is_editable")

    default_display_mode = fields.Selection(
        string="Default Display Mode",
        selection=[("video_full_screen", "Full screen video")],
        help="Determines how the channel will be displayed by default when opening it from its invitation link. No value means display text (no voice/video).",
    )

    description = fields.Text("Description")

    image_128 = fields.Image("Image", max_width=128, max_height=128)

    avatar_128 = fields.Image(
        "Avatar",
        max_width=128,
        max_height=128,
        compute="_compute_avatar_128",
    )

    avatar_cache_key = fields.Char(compute="_compute_avatar_cache_key")

    channel_partner_ids: ResPartner = fields.Many2many(
        "res.partner",
        string="Partners",
        compute="_compute_channel_partner_ids",
        inverse="_inverse_channel_partner_ids",
        search="_search_channel_partner_ids",
    )

    channel_member_ids: DiscussChannelMember = fields.One2many(
        "discuss.channel.member",
        "channel_id",
        string="Members",
    )

    parent_channel_id: DiscussChannel = fields.Many2one(
        "discuss.channel",
        help="Parent channel",
        ondelete="cascade",
        index=True,
        bypass_search_access=True,
        readonly=True,
        copy=False,
    )

    sub_channel_ids: DiscussChannel = fields.One2many(
        "discuss.channel",
        "parent_channel_id",
        string="Sub Channels",
        readonly=True,
    )

    from_message_id: MailMessage = fields.Many2one(
        "mail.message",
        help="The message the channel was created from.",
        readonly=True,
        copy=False,
    )

    pinned_message_ids: MailMessage = fields.One2many(
        "mail.message",
        "res_id",
        domain=[("model", "=", "discuss.channel"), ("pinned_at", "!=", False)],
        string="Pinned Messages",
    )

    sfu_channel_uuid = fields.Char(groups="base.group_system")

    sfu_server_url = fields.Char(groups="base.group_system")

    rtc_session_ids: DiscussChannelRtcSession = fields.One2many(
        "discuss.channel.rtc.session", "channel_id", groups="base.group_system"
    )

    call_history_ids: DiscussCallHistory = fields.One2many(
        "discuss.call.history", "channel_id"
    )

    is_member = fields.Boolean(
        "Is Member",
        compute="_compute_is_member",
        search="_search_is_member",
        compute_sudo=True,
    )

    self_member_id: DiscussChannelMember = fields.Many2one(
        "discuss.channel.member",
        compute="_compute_self_member_id",
        compute_sudo=True,
    )

    invited_member_ids: DiscussChannelMember = fields.One2many(
        "discuss.channel.member",
        compute="_compute_invited_member_ids",
        compute_sudo=True,
    )

    member_count = fields.Integer(
        string="Member Count",
        compute="_compute_member_count",
        compute_sudo=True,
    )

    message_count = fields.Integer(
        "# Messages",
        readonly=True,
        compute="_compute_message_count",
    )

    last_interest_dt = fields.Datetime(
        "Last Interest",
        default=lambda self: fields.Datetime.now() - timedelta(seconds=1),
        index=True,
        help="Contains the date and time of the last interesting event that happened in this channel. This updates itself when new message posted.",
    )

    group_ids: ResGroups = fields.Many2many(
        "res.groups",
        string="Auto Subscription",
        help="Members of those groups will automatically added as followers. "
        "Note that they will be able to manage their subscription manually "
        "if necessary.",
    )

    uuid = fields.Char(
        "UUID", size=50, default=lambda self: self._default_uuid(), copy=False
    )

    group_public_id: ResGroups = fields.Many2one(
        "res.groups",
        string="Authorized Group",
        compute="_compute_group_public_id",
        recursive=True,
        readonly=False,
        store=True,
    )

    invitation_url = fields.Char("Invitation URL", compute="_compute_invitation_url")

    channel_name_member_ids: DiscussChannelMember = fields.One2many(
        "discuss.channel.member",
        compute="_compute_channel_name_member_ids",
        help="Members from which the channel name is computed when the name field is empty.",
    )

    _from_message_id_unique = models.Constraint(
        "UNIQUE(from_message_id)",
        "Messages can only be linked to one sub-channel",
    )

    _uuid_unique = models.Constraint(
        "UNIQUE(uuid)",
        "The channel UUID must be unique",
    )

    _group_public_id_check = models.Constraint(
        "CHECK (channel_type = 'channel' OR group_public_id IS NULL)",
        "Group authorization and group auto-subscription are only supported on channels.",
    )

    @api.constrains("from_message_id")
    def _constraint_from_message_id(self) -> None:
        if failing_channels := self.sudo().filtered(
            lambda c: (
                c.from_message_id
                and (
                    c.from_message_id.res_id
                    not in [c.parent_channel_id.id]
                    + c.parent_channel_id.sub_channel_ids.ids
                    or c.from_message_id.model != "discuss.channel"
                )
            )
        ):
            raise ValidationError(
                self.env._(
                    "Cannot create %(channels)s: initial message should belong to parent channel or one of its sub-channels.",
                    channels=failing_channels.mapped("name"),
                )
            )

    @api.constrains("parent_channel_id")
    def _constraint_parent_channel_id(self) -> None:
        if failing_channels := self.sudo().filtered(
            lambda c: (
                c.parent_channel_id
                and (
                    c.parent_channel_id.parent_channel_id
                    or c.parent_channel_id.channel_type not in ["channel", "group"]
                    or c.parent_channel_id.channel_type != c.channel_type
                )
            )
        ):
            raise ValidationError(
                self.env._(
                    "Cannot create %(channels)s: parent should not be a sub-channel and should be of type 'channel' or 'group'. The sub-channel should have the same type as the parent.",
                    channels=failing_channels.mapped("name"),
                ),
            )

    @api.constrains("channel_member_ids")
    def _constraint_partners_chat(self) -> None:
        for ch in self.sudo().filtered(lambda ch: ch.channel_type == "chat"):
            if len(ch.channel_member_ids) > 2:
                raise ValidationError(
                    self.env._(
                        "A channel of type 'chat' cannot have more than two users."
                    )
                )

    @api.constrains("group_public_id", "group_ids")
    def _constraint_group_id_channel(self) -> None:
        failing_channels = self.sudo().filtered(
            lambda channel: (
                channel.channel_type != "channel"
                and (channel.group_public_id or channel.group_ids)
            )
        )
        if failing_channels:
            raise ValidationError(
                self.env._(
                    "For %(channels)s, channel_type should be 'channel' to have the group-based authorization or group auto-subscription.",
                    channels=", ".join([ch.name for ch in failing_channels]),
                )
            )

    @api.model
    def _default_uuid(self) -> str:
        return token_urlsafe(16)

    @api.model
    def _get_allowed_channel_member_create_params(self) -> list:
        return ["partner_id", "guest_id", "unpin_dt", "last_interest_dt"]

    @api.model
    def _check_member_commands(
        self, commands: Any, allowed_codes: tuple[int, ...], error_message: str
    ) -> None:
        for command in commands:
            if (
                not isinstance(command, list | tuple)
                or len(command) < 2
                or command[0] not in allowed_codes
                or (command[0] in (0, 6) and len(command) < 3)
            ):
                raise ValidationError(error_message)

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        for vals in vals_list:
            partner_ids_cmd = vals.get("channel_partner_ids") or []
            self._check_member_commands(
                partner_ids_cmd,
                (4, 6),
                self.env._(
                    "Invalid value when creating a channel with members, only 4 or 6 are allowed."
                ),
            )
            partner_ids = [cmd[1] for cmd in partner_ids_cmd if cmd[0] == 4]
            partner_ids += [
                pid for cmd in partner_ids_cmd if cmd[0] == 6 for pid in cmd[2]
            ]

            membership_ids_cmd = vals.get("channel_member_ids", [])
            self._check_member_commands(
                membership_ids_cmd,
                (0,),
                self.env._(
                    "Invalid value when creating a channel with memberships, only 0 is allowed."
                ),
            )
            for cmd in membership_ids_cmd:
                for field_name in cmd[2]:
                    if (
                        field_name
                        not in self._get_allowed_channel_member_create_params()
                    ):
                        raise ValidationError(
                            self.env._(
                                "Invalid field “%(field_name)s” when creating a channel with members.",
                                field_name=field_name,
                            )
                        )
            membership_pids = [
                cmd[2]["partner_id"]
                for cmd in membership_ids_cmd
                if cmd[0] == 0 and "partner_id" in cmd[2]
            ]

            partner_ids_to_add = partner_ids
            if (
                not self.env.context.get("install_mode")
                and not self.env.user._is_public()
            ):
                partner_ids_to_add = list(
                    set(partner_ids + [self.env.user.partner_id.id])
                )
            vals["channel_member_ids"] = membership_ids_cmd + [
                (0, 0, {"partner_id": pid})
                for pid in partner_ids_to_add
                if pid not in membership_pids
            ]

            vals.pop("channel_partner_ids", False)

        channels = super(
            DiscussChannel,
            self.with_context(
                mail_create_bypass_create_check=self.env[
                    "discuss.channel.member"
                ]._bypass_create_check,
                mail_create_nolog=True,
                mail_create_nosubscribe=True,
            ),
        ).create(vals_list)
        channels = channels.with_context(mail_create_bypass_create_check=None)
        channels._subscribe_users_automatically()
        if not self.env.context.get("install_mode") and not self.env.user._is_public():
            Store(bus_channel=self.env.user).add(channels).bus_send()
        return channels

    def write(self, vals: ValuesType) -> Literal[True]:
        self._check_write_allowed(vals)
        targets = self
        if "group_public_id" in vals:
            targets |= self.sudo().sub_channel_ids
        sync_field_names, old_vals = self._prepare_sync_snapshot(vals, targets)
        result = super().write(vals)
        self._notify_sync_diffs(sync_field_names, old_vals)
        if vals.get("group_ids"):
            self._subscribe_users_automatically()
        return result

    def _check_write_allowed(self, vals: ValuesType) -> None:
        if not self.env.is_admin() and self._STRUCTURAL_WRITE_FIELDS & vals.keys():
            if non_member := self.filtered(lambda channel: not channel.self_member_id):
                raise AccessError(
                    self.env._(
                        "You must be a member of %(channels)s to modify its "
                        "configuration.",
                        channels=", ".join(non_member.mapped("name")),
                    )
                )
        if "channel_type" in vals:
            if failing_channels := self.filtered(
                lambda channel: channel.channel_type != vals.get("channel_type")
            ):
                raise UserError(
                    self.env._(
                        "Cannot change the channel type of: %(channel_names)s",
                        channel_names=", ".join(failing_channels.mapped("name")),
                    )
                )
        if immutable := {"from_message_id", "parent_channel_id"} & set(vals):
            if failing_channels := self.filtered(
                lambda channel: any(
                    channel[name].id != (vals[name] or False) for name in immutable
                )
            ):
                raise UserError(
                    self.env._(
                        "Cannot change initial message nor parent channel of: %(channels)s.",
                        channels=", ".join(failing_channels.mapped("name")),
                    )
                )
        if "group_public_id" in vals:
            if failing_channels := self.filtered(
                lambda channel: channel.parent_channel_id
            ):
                raise UserError(
                    self.env._(
                        "Cannot change authorized group of sub-channel: %(channels)s.",
                        channels=failing_channels.mapped("name"),
                    )
                )

    def _sync_field_names(self) -> defaultdict[str | None, list[StoreFieldSpec]]:
        res = defaultdict(list)
        res[None] += [
            Store.Attr("avatar_cache_key", predicate=is_channel_or_group),
            "channel_type",
            "create_uid",
            "default_display_mode",
            Store.Attr("description", predicate=is_channel_or_group),
            Store.Many("group_ids", [], predicate=is_channel),
            Store.One("group_public_id", predicate=is_channel),
            "last_interest_dt",
            "member_count",
            "name",
            "uuid",
        ]
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_all_employee_channel(self) -> None:
        try:
            all_emp_group = self.env.ref("mail.channel_all_employees")
        except ValueError:
            all_emp_group = None
        if all_emp_group and all_emp_group in self:
            raise UserError(
                self.env._(
                    "You cannot delete those groups, as the Whole Company group is required by other modules."
                )
            )
        for channel in self:
            channel._bus_send("discuss.channel/delete", {"id": channel.id})

    @api.depends("channel_name_member_ids", "name")
    def _compute_display_name(self) -> None:
        for channel in self:
            if channel.name:
                channel.display_name = channel.name
                continue
            parts = channel.channel_name_member_ids.mapped(
                lambda m: m.partner_id.name or m.guest_id.name
            )
            if channel.member_count > 3:
                remaining = channel.member_count - 3
                parts.append(
                    self.env._("1 other")
                    if remaining == 1
                    else self.env._("%s others", remaining)
                )
            channel.display_name = format_list(self.env, parts)

    @api.depends("channel_member_ids")
    def _compute_channel_name_member_ids(self) -> None:
        to_compute = self.filtered(
            lambda c: c.channel_type in self._member_based_naming_channel_types()
        )
        (self - to_compute).channel_name_member_ids = False
        if not to_compute:
            return
        self.env["discuss.channel.member"].flush_model(["channel_id"])
        self.env.cr.execute(
            """
            SELECT channel.id, member.id
              FROM discuss_channel channel
      JOIN LATERAL
                (
                   SELECT id
                     FROM discuss_channel_member M
                    WHERE M.channel_id = channel.id
                 ORDER BY id
                    LIMIT 3
                ) as member ON TRUE
             WHERE channel.id = ANY(%s)
        """,
            (list(to_compute.ids),),
        )
        channel_id_to_member_ids = defaultdict(list)
        for channel_id, member_id in self.env.cr.fetchall():
            channel_id_to_member_ids[channel_id].append(member_id)
        for channel in to_compute:
            channel.channel_name_member_ids = channel_id_to_member_ids.get(channel.id)

    @api.depends("channel_type", "is_member", "group_public_id")
    @api.depends_context("uid")
    def _compute_is_editable(self) -> None:
        existing = self.filtered("id")
        new = self - existing
        if new:
            can_write = self.env["discuss.channel"].has_access("write")
            for channel in new:
                channel.is_editable = can_write
        editable = existing._filtered_access("write")
        is_admin = self.env.is_admin()
        for channel in existing:
            channel.is_editable = channel in editable and (
                is_admin or channel.is_member
            )

    def _generate_avatar(self) -> bytes | Literal[False]:
        self.ensure_one()
        if not is_channel_or_group(self):
            return False
        avatar = GROUP_AVATAR if self.channel_type == "group" else CHANNEL_AVATAR
        bgcolor = hsl_from_seed(self.uuid)
        avatar = avatar.replace('fill="#875a7b"', f'fill="{bgcolor}"')
        return base64.b64encode(avatar.encode())

    @api.depends("channel_type", "image_128", "uuid")
    def _compute_avatar_128(self) -> None:
        for record in self:
            record.avatar_128 = record.image_128 or record._generate_avatar()

    def _get_image_128_checksums(self) -> dict[int, str]:
        stored = self.filtered("id")
        if not stored:
            return {}
        stored.flush_recordset(["image_128"])
        return {
            attachment["res_id"]: attachment["checksum"]
            for attachment in self.env["ir.attachment"]
            .sudo()
            .search_read(
                [
                    ("res_model", "=", "discuss.channel"),
                    ("res_field", "=", "image_128"),
                    ("res_id", "in", stored.ids),
                ],
                ["checksum", "res_id"],
            )
        }

    @api.depends("channel_type", "image_128", "uuid")
    def _compute_avatar_cache_key(self) -> None:
        checksums = self._get_image_128_checksums()
        for channel in self:
            if channel.id in checksums:
                channel.avatar_cache_key = (
                    checksums[channel.id] or sha512(channel.avatar_128).hexdigest()
                )
            elif not channel.id:
                channel.avatar_cache_key = (
                    sha512(channel.avatar_128).hexdigest()
                    if channel.avatar_128
                    else "no-avatar"
                )
            elif is_channel_or_group(channel):
                channel.avatar_cache_key = sha512(
                    f"{channel.channel_type}/{channel.uuid}".encode()
                ).hexdigest()
            else:
                channel.avatar_cache_key = "no-avatar"

    @api.depends("channel_member_ids.partner_id")
    def _compute_channel_partner_ids(self) -> None:
        for channel in self:
            channel.channel_partner_ids = channel.channel_member_ids.partner_id

    @api.depends_context("uid", "guest")
    @api.depends("channel_member_ids")
    def _compute_is_member(self) -> None:
        for channel in self:
            channel.is_member = bool(channel.self_member_id)

    @api.depends_context("uid", "guest")
    @api.depends("channel_member_ids")
    def _compute_self_member_id(self) -> None:
        member_by_channel = {
            channel: self.env["discuss.channel.member"].browse(member_id)
            for channel, member_id in self.env["discuss.channel.member"]._read_group(
                [("channel_id", "in", self.ids), ("is_self", "=", True)],
                ["channel_id"],
                ["id:max"],
            )
        }
        for channel in self:
            channel.self_member_id = member_by_channel.get(channel)

    @api.depends("channel_member_ids.rtc_inviting_session_id")
    def _compute_invited_member_ids(self) -> None:
        members_by_channel = {
            channel: self.env["discuss.channel.member"].browse(member_ids)
            for channel, member_ids in self.env["discuss.channel.member"]._read_group(
                [
                    ("channel_id", "in", self.ids),
                    ("rtc_inviting_session_id", "!=", False),
                ],
                ["channel_id"],
                ["id:array_agg"],
            )
        }
        for channel in self:
            channel.invited_member_ids = members_by_channel.get(channel)

    @api.depends("channel_member_ids")
    def _compute_member_count(self) -> None:
        read_group_res = self.env["discuss.channel.member"]._read_group(
            domain=[("channel_id", "in", self.ids)],
            groupby=["channel_id"],
            aggregates=["__count"],
        )
        member_count_by_channel_id = {
            channel.id: count for channel, count in read_group_res
        }
        for channel in self:
            channel.member_count = member_count_by_channel_id.get(channel.id, 0)

    @api.depends("message_ids")
    def _compute_message_count(self) -> None:
        read_group_res = self.env["mail.message"]._read_group(
            domain=[
                ("model", "=", "discuss.channel"),
                ("res_id", "in", self.ids),
                ("message_type", "not in", ["user_notification", "notification"]),
            ],
            groupby=["res_id"],
            aggregates=["__count"],
        )
        message_count_by_channel_id = dict(read_group_res)
        for channel in self:
            channel.message_count = message_count_by_channel_id.get(channel.id, 0)

    @api.depends("channel_type", "parent_channel_id.group_public_id")
    def _compute_group_public_id(self) -> None:
        channels = self.filtered(lambda channel: channel.channel_type == "channel")
        for channel in channels:
            if channel.parent_channel_id:
                channel.group_public_id = channel.parent_channel_id.group_public_id
            elif not channel.group_public_id:
                channel.group_public_id = self.env.ref("base.group_user")
        (self - channels).group_public_id = None

    @api.depends("uuid")
    def _compute_invitation_url(self) -> None:
        for channel in self:
            channel.invitation_url = f"/chat/{channel.id}/{channel.uuid}"

    def _search_channel_partner_ids(self, operator: str, operand: Any) -> list:
        return [("channel_member_ids", "any", [("partner_id", operator, operand)])]

    def _search_is_member(
        self, operator: str, operand: Any
    ) -> list | NotImplementedType:
        if operator != "in":
            return NotImplemented
        return Domain("channel_member_ids", "any", [("is_self", "=", True)])

    def _inverse_channel_partner_ids(self) -> None:
        new_members = []
        outdated = self.env["discuss.channel.member"]
        for channel in self:
            current_members = channel.channel_member_ids
            partners = channel.channel_partner_ids
            partners_new = partners - current_members.partner_id

            new_members += [
                {
                    "channel_id": channel.id,
                    "partner_id": partner.id,
                }
                for partner in partners_new
            ]
            outdated += current_members.filtered(
                lambda m, partners=partners: (
                    m.partner_id and m.partner_id not in partners
                )
            )
        if new_members:
            self.env["discuss.channel.member"].create(new_members)
        if outdated:
            outdated._unlink_and_notify()

    def action_unfollow(self) -> None:
        partner, guest = self.env["res.partner"]._get_current_persona()
        self._action_unfollow(partner=partner, guest=guest)

    def _get_notification_member_domain(
        self, pids: list[int], author_id: int | Literal[False]
    ) -> Domain:
        self.ensure_one()
        settings = "partner_id.user_ids.res_users_settings_ids.channel_notifications"
        opted_in = Domain("custom_notifications", "=", "all") | (
            Domain("custom_notifications", "=", False) & Domain(settings, "=", "all")
        )
        mentioned = Domain("partner_id", "in", pids) & (
            Domain("custom_notifications", "=", "mentions")
            | (
                Domain("custom_notifications", "=", False)
                & Domain(settings, "=", False)
            )
        )
        return (
            Domain("channel_id", "=", self.id)
            & Domain("partner_id", "!=", author_id)
            & Domain("partner_id.active", "=", True)
            & (
                Domain("mute_until_dt", "=", False)
                | Domain("mute_until_dt", "<=", fields.Datetime.now())
            )
            & Domain("partner_id.user_ids.manual_im_status", "!=", "busy")
            & (
                Domain("channel_id.channel_type", "!=", "channel")
                | (
                    Domain("channel_id.channel_type", "=", "channel")
                    & (opted_in | mentioned)
                )
            )
        )

    def _notify_get_recipients(
        self, message: MailMessage, msg_vals: dict | Literal[False] = False, **kwargs
    ) -> list:
        self.ensure_one()
        msg_vals = msg_vals or {}

        message_type = msg_vals.get("message_type", message.message_type)
        if message_type not in (
            "comment",
            "email",
            "email_outgoing",
            "whatsapp_message",
        ):
            return []

        author_id = msg_vals.get("author_id") or message.author_id.id
        pids = (
            msg_vals["partner_ids"] or []
            if "partner_ids" in msg_vals
            else message.partner_ids.ids
        )
        email_from = tools.email_normalize(
            msg_vals.get("email_from") or message.email_from
        )
        recipients_data = self._get_mentioned_recipients_data(
            pids, author_id, email_from
        )
        domain = self._get_notification_member_domain(pids, author_id)
        members = self.env["discuss.channel.member"].sudo().search(domain)
        recipients_data.extend(
            build_recipient_data(
                partner_id=member.partner_id.id,
                email_normalized=member.partner_id.email_normalized,
                lang=member.partner_id.lang,
                name=member.partner_id.name,
                notif="web_push",
                partner_share=member.partner_id.partner_share,
            )
            for member in members
        )
        return recipients_data

    def _get_mentioned_recipients_data(
        self, pids: list[int], author_id: int | Literal[False], email_from: str | None
    ) -> list[dict]:
        if not pids:
            return []
        self.env["res.partner"].flush_model(
            ["active", "email", "email_normalized", "partner_share"]
        )
        self.env["res.users"].flush_model(["notification_type", "partner_id"])
        self.env.cr.execute(
            SQL(
                """
                SELECT DISTINCT ON (partner.id) partner.id,
                       partner.email_normalized,
                       partner.lang,
                       partner.name,
                       partner.partner_share,
                       users.id as uid,
                       COALESCE(users.notification_type, 'email') as notif,
                       COALESCE(users.share, FALSE) as ushare
                  FROM res_partner partner
             LEFT JOIN res_users users on partner.id = users.partner_id
                 WHERE partner.active IS TRUE
                       -- Compare like with like: the bound author address is
                       -- normalized, while partner.email holds whatever was
                       -- typed (mixed case, or a full "Name <addr>" form).
                       -- Matching the raw column suppressed only byte-exact
                       -- duplicates, so a second partner record for the
                       -- message's own author still got notified of their own
                       -- message. email_normalized is stored and btree-indexed,
                       -- so this is also the cheaper comparison.
                       AND partner.email_normalized IS DISTINCT FROM %(email)s
                       AND partner.id IN %(partner_ids)s AND partner.id != %(author_id)s
                       -- DISTINCT ON without a matching ORDER BY returns whichever
                       -- row Postgres reaches first, so a partner owning two user
                       -- accounts was notified by inbox or by email depending on
                       -- heap order -- a HOT update or autovacuum flipped it. Order
                       -- internal before portal, then by id, so the answer is both
                       -- stable and the better of the two.
                  ORDER BY partner.id, COALESCE(users.share, FALSE), users.id
                """,
                email=email_from or "",
                partner_ids=tuple(pids),
                author_id=author_id or 0,
            )
        )
        return [
            build_recipient_data(
                partner_id=partner_id,
                email_normalized=email_normalized,
                lang=lang,
                name=name,
                notif=notif,
                partner_share=partner_share,
                uid=uid,
                user_share=ushare,
            )
            for (
                partner_id,
                email_normalized,
                lang,
                name,
                partner_share,
                uid,
                notif,
                ushare,
            ) in self.env.cr.fetchall()
        ]

    def _notify_get_recipients_groups(
        self,
        message: MailMessage,
        model_description: str,
        msg_vals: dict | Literal[False] = False,
    ) -> list:
        groups = super()._notify_get_recipients_groups(
            message, model_description, msg_vals=msg_vals
        )
        for index, (group_name, _group_func, group_data) in enumerate(groups):
            if group_name != "customer":
                groups[index] = (group_name, lambda partner: False, group_data)
        return groups

    def _get_notify_valid_parameters(self) -> set[str]:
        return super()._get_notify_valid_parameters() | {"silent"}

    def _notify_thread(
        self, message: MailMessage, msg_vals: dict | Literal[False] = False, **kwargs
    ) -> list[dict]:
        rdata = super()._notify_thread(message, msg_vals=msg_vals, **kwargs)
        payload = {
            "data": Store(bus_channel=self).add(message).get_result(),
            "id": self.id,
            "message_id": message.id,
        }
        if temporary_id := self.env.context.get("temporary_id"):
            payload["temporary_id"] = temporary_id
        if kwargs.get("silent"):
            payload["silent"] = True
        self._bus_send("discuss.channel/new_message", payload)
        return rdata

    def _notify_by_web_push_prepare_payload(
        self,
        message: MailMessage,
        msg_vals: dict | Literal[False] = False,
        force_record_name: str | Literal[False] = False,
    ) -> dict:
        payload = super()._notify_by_web_push_prepare_payload(
            message,
            msg_vals=msg_vals,
            force_record_name=force_record_name,
        )
        msg_vals = msg_vals or {}
        payload["options"]["data"]["action"] = "mail.action_discuss"
        record_name = force_record_name or message.record_name
        author_ids = (
            [msg_vals["author_id"]]
            if msg_vals.get("author_id")
            else message.author_id.ids
        )
        author = self.env["res.partner"].browse(author_ids) or self.env[
            "mail.guest"
        ].browse(msg_vals.get("author_guest_id", message.author_guest_id.id))
        if self.channel_type == "chat":
            payload["title"] = author.name
        elif self.channel_type == "channel":
            payload["title"] = "#%s - %s" % (record_name, author.name)
        elif self.channel_type == "group":
            if not record_name:
                member_names = self.channel_member_ids.mapped(
                    lambda m: m.partner_id.name if m.partner_id else m.guest_id.name
                )
                record_name = (
                    f"{', '.join(member_names[:-1])} and {member_names[-1]}"
                    if len(member_names) > 1
                    else member_names[0]
                    if member_names
                    else ""
                )
            payload["title"] = "%s - %s" % (record_name, author.name)
        else:
            payload["title"] = "#%s" % (record_name)
        return payload

    def _notify_thread_by_web_push(
        self,
        message: MailMessage,
        recipients_data: list[dict],
        msg_vals: dict | Literal[False] = False,
        **kwargs,
    ) -> None:
        super()._notify_thread_by_web_push(
            message,
            [r for r in recipients_data if r["notif"] == "web_push"],
            msg_vals=msg_vals,
            **kwargs,
        )

    def _message_receive_bounce(self, email: str, partner: ResPartner) -> None:
        if self.channel_type in self._types_allowing_unfollow():
            for p in partner:
                if p.message_bounce >= self.MAX_BOUNCE_LIMIT:
                    self._action_unfollow(p)
        return super()._message_receive_bounce(email, partner)

    def _get_allowed_message_params(self) -> set[str]:
        return super()._get_allowed_message_params() | {"special_mentions", "parent_id"}

    def _get_allowed_message_partner_ids(self, partner_ids: list[int]) -> list[int]:
        self.ensure_one()
        partners = self.env["res.partner"].browse(partner_ids)
        if is_channel(self):
            if self.group_public_id:
                allowed = set(
                    self.env["res.partner"]
                    .search(
                        [
                            ("id", "in", partners.ids),
                            ("user_ids.all_group_ids", "in", self.group_public_id.ids),
                        ]
                    )
                    .ids
                )
                return [pid for pid in partners.ids if pid in allowed]
        else:
            partners = (
                self.env["discuss.channel.member"]
                .search_fetch(
                    [("channel_id", "=", self.id), ("partner_id", "in", partner_ids)],
                    ["partner_id"],
                )
                .partner_id
            )
        return partners.ids

    def message_post(
        self,
        *,
        message_type: str = "notification",
        partner_ids: list[int] | None = None,
        **kwargs,
    ) -> MailMessage:
        if message_type not in ["notification", "user_notification"]:
            self.sudo().last_interest_dt = fields.Datetime.now()
        if "everyone" in kwargs.pop("special_mentions", []):
            partner_ids = list(
                OrderedSet((partner_ids or []) + self.channel_member_ids.partner_id.ids)
            )
        if partner_ids:
            kwargs["partner_ids"] = self._get_allowed_message_partner_ids(partner_ids)
        return super(
            DiscussChannel,
            self.with_context(
                mail_post_autofollow_author_skip=True, mail_post_autofollow=False
            ),
        ).message_post(message_type=message_type, **kwargs)

    def _partner_wants_channel_notifications(self, partner: ResPartner) -> bool:
        return not partner.user_ids or any(
            user.res_users_settings_id.channel_notifications != "no_notif"
            for user in partner.user_ids
        )

    def _message_post_after_hook(self, message: MailMessage, msg_vals: dict) -> None:
        if self.self_member_id and message.is_current_user_or_guest_author:
            self.self_member_id._set_last_seen_message(message, notify=False)
            self.self_member_id._set_new_message_separator(message.id + 1)
        if self.parent_channel_id and message.partner_ids:
            members = self.env["discuss.channel.member"].search(
                [
                    ("channel_id", "=", self.parent_channel_id.id),
                    ("partner_id", "in", message.partner_ids.ids),
                ]
            )
            to_invite = members.filtered(
                lambda m: (
                    m.custom_notifications != "no_notif"
                    if m.custom_notifications
                    else self._partner_wants_channel_notifications(m.partner_id)
                )
            ).partner_id
            if self.parent_channel_id.channel_type == "channel":
                to_invite |= (message.partner_ids - members.partner_id).filtered(
                    self._partner_wants_channel_notifications
                )
            self._add_members(partners=to_invite)
        return super()._message_post_after_hook(message, msg_vals)

    def _message_update_content(
        self, message: MailMessage, /, *, partner_ids: list[int] | None = None, **kwargs
    ) -> None:
        if partner_ids:
            kwargs["partner_ids"] = self._get_allowed_message_partner_ids(partner_ids)
        super()._message_update_content(message, **kwargs)

    def _check_can_update_message_content(self, message: MailMessage) -> None:
        if not message.message_type == "comment":
            raise UserError(
                self.env._(
                    "Only messages type comment can have their content updated on model 'discuss.channel'"
                )
            )

    def _create_attachments_for_post(
        self, values_list: list[dict], extra_list: list[tuple]
    ) -> IrAttachment:
        attachments = super()._create_attachments_for_post(values_list, extra_list)
        voice = attachments.env["ir.attachment"]
        for attachment, (_cid, _name, _token, info) in zip(
            attachments, extra_list, strict=True
        ):
            if info.get("voice"):
                voice += attachment
        if voice:
            voice._set_voice_metadata()
        return attachments

    def _message_subscribe(
        self,
        partner_ids: list[int] | None = None,
        subtype_ids: list[int] | None = None,
        customer_ids: list[int] | None = None,
    ) -> NoReturn:
        raise UserError(
            self.env._(
                "Adding followers on channels is not possible. Consider adding members instead."
            )
        )

    def _clean_empty_message(self, message: MailMessage) -> None:
        super()._clean_empty_message(message)
        message.parent_id = False

    def _get_store_message_update_extra_fields(self) -> list[StoreFieldSpec]:
        return super()._get_store_message_update_extra_fields() + [
            Store.One("parent_id")
        ]

    def _get_last_messages(self) -> MailMessage:
        if not self.ids:
            return self.env["mail.message"]
        self.env["mail.message"].flush_model(["model", "res_id"])
        self.env.cr.execute(
            """
                   SELECT last_message_id
                     FROM discuss_channel
        LEFT JOIN LATERAL (
                              SELECT id
                                FROM mail_message
                               WHERE mail_message.model = 'discuss.channel'
                                 AND mail_message.res_id = discuss_channel.id
                            ORDER BY id DESC
                               LIMIT 1
                          ) AS t(last_message_id) ON TRUE
                    WHERE discuss_channel.id = ANY(%(ids)s)
                 GROUP BY discuss_channel.id, t.last_message_id
                 ORDER BY discuss_channel.id
            """,
            {"ids": list(self.ids)},
        )
        return self.env["mail.message"].browse(
            [mid for (mid,) in self.env.cr.fetchall() if mid]
        )

    def set_message_pin(self, message_id: int, pinned: bool) -> None:
        self.ensure_one()
        if not self.env.is_admin() and not self.self_member_id:
            raise AccessError(
                self.env._(
                    "You must be a member of this channel to pin or unpin messages."
                )
            )
        message_to_update = self.env["mail.message"].search(
            [
                ["id", "=", message_id],
                ["model", "=", "discuss.channel"],
                ["res_id", "=", self.id],
                ["pinned_at", "=" if pinned else "!=", False],
            ]
        )
        if not message_to_update:
            return
        message_to_update.flush_recordset(["pinned_at"])
        self.env.cr.execute(
            "UPDATE mail_message SET pinned_at=%s WHERE id=%s",
            (fields.Datetime.now() if pinned else None, message_to_update.id),
        )
        message_to_update.invalidate_recordset(["pinned_at"])

        Store(bus_channel=self).add(message_to_update, "pinned_at").bus_send()
        if pinned:
            notification_text = """
                <div data-oe-type="pin" class="o_mail_notification">
                    %(user_pinned_a_message_to_this_channel)s
                    <a href="#" data-oe-type="pin-menu">%(see_all_pins)s</a>
                </div>
            """
            notification = Markup(notification_text) % {
                "user_pinned_a_message_to_this_channel": Markup(
                    '<a href="#" data-oe-type="highlight" data-oe-id="%s">%s</a>'
                )
                % (
                    message_id,
                    self.env._(
                        "%(user_name)s pinned a message to this channel.",
                        user_name=(
                            self.self_member_id._get_html_link_title()
                            or self.env.user.display_name
                        ),
                    ),
                ),
                "see_all_pins": self.env._("See all pinned messages."),
            }
            self.message_post(
                body=notification,
                message_type="notification",
                subtype_xmlid="mail.mt_comment",
            )

    def _action_unfollow(
        self,
        partner: ResPartner | None = None,
        guest: MailGuest | None = None,
        post_leave_message: bool = True,
    ) -> None:
        self.ensure_one()
        if partner is None:
            partner = self.env["res.partner"]
        if guest is None:
            guest = self.env["mail.guest"]
        if not partner and not guest:
            raise ValueError(
                "_action_unfollow requires a partner or a guest to unfollow"
            )
        member = self.env["discuss.channel.member"].search(
            [
                ("channel_id", "=", self.id),
                ("partner_id", "=", partner.id)
                if partner
                else ("guest_id", "=", guest.id),
            ]
        )
        if not member:
            return
        self.message_unsubscribe(partner.ids)
        if self.channel_type != "channel" and post_leave_message:
            notification = Markup(
                '<div class="o_mail_notification" data-oe-type="channel-left">%s</div>'
            ) % self.env._("left the channel")
            member.channel_id.sudo().with_context(
                guest=guest or self.env.context.get("guest")
            ).message_post(
                body=notification,
                subtype_xmlid="mail.mt_comment",
                author_id=partner.id or None,
            )
        member._unlink_and_notify()

    def add_members(
        self,
        partner_ids: list[int] | None = None,
        guest_ids: list[int] | None = None,
        invite_to_rtc_call: bool = False,
        post_joined_message: bool = True,
    ) -> DiscussChannelMember:
        return self._add_members(
            partners=self.env["res.partner"].browse(partner_ids or []).exists(),
            guests=self.env["mail.guest"].browse(guest_ids or []).exists(),
            invite_to_rtc_call=invite_to_rtc_call,
            post_joined_message=post_joined_message,
        )

    def _add_members(
        self,
        *,
        guests: MailGuest | None = None,
        partners: ResPartner | None = None,
        users: ResUsers | None = None,
        create_member_params: dict | None = None,
        invite_to_rtc_call: bool = False,
        post_joined_message: bool = True,
        inviting_partner: ResPartner | None = None,
    ) -> DiscussChannelMember:
        inviting_partner = inviting_partner or self.env["res.partner"]
        partners = partners or self.env["res.partner"]
        if users:
            partners |= users.partner_id
        guests = guests or self.env["mail.guest"]
        current_partner, current_guest = self.env["res.partner"]._get_current_persona()
        existing_by_channel = self._get_existing_members_by_channel(partners, guests)
        all_new_members, new_members_by_channel = self._create_missing_members(
            partners, guests, existing_by_channel, create_member_params
        )
        for channel in self:
            new_members = new_members_by_channel[channel]
            existing_members = existing_by_channel[channel]
            self._notify_members_joined(new_members, invite_to_rtc_call)
            if (
                new_members
                and channel.channel_type != "channel"
                and post_joined_message
            ):
                channel._post_joined_messages(new_members, inviting_partner)
            if new_members:
                Store(bus_channel=channel).add(channel, "member_count").add(
                    new_members
                ).bus_send()
            if existing_members and (
                bus_channel := current_partner.main_user_id or current_guest
            ):
                Store(
                    bus_channel=bus_channel,
                ).add(channel, "member_count").add(existing_members).bus_send()
        if invite_to_rtc_call:
            self._invite_new_members_to_call(new_members_by_channel)
        return all_new_members

    def _get_existing_members_by_channel(
        self, partners: ResPartner, guests: MailGuest
    ) -> dict:
        Member = self.env["discuss.channel.member"]
        by_channel = defaultdict(lambda: Member)
        members = Member.search(
            Domain("channel_id", "in", self.ids)
            & (
                Domain("partner_id", "in", partners.ids)
                | Domain("guest_id", "in", guests.ids)
            )
        )
        for member in members:
            by_channel[member.channel_id] |= member
        return by_channel

    def _get_parent_channel_personas(
        self, partners: ResPartner, guests: MailGuest
    ) -> defaultdict[int | Literal[False], set[tuple[str, int]]]:
        admitted = defaultdict(set)
        parents = self.parent_channel_id
        if not parents or not (partners or guests):
            return admitted
        members = (
            self.env["discuss.channel.member"]
            .sudo()
            .search_fetch(
                Domain("channel_id", "in", parents.ids)
                & (
                    Domain("partner_id", "in", partners.ids)
                    | Domain("guest_id", "in", guests.ids)
                ),
                ["channel_id", "partner_id", "guest_id"],
            )
        )
        for member in members:
            key = (
                ("partner", member.partner_id.id)
                if member.partner_id
                else ("guest", member.guest_id.id)
            )
            admitted[member.channel_id.id].add(key)
        return admitted

    def _create_missing_members(
        self,
        partners: ResPartner,
        guests: MailGuest,
        existing_by_channel: dict,
        create_member_params: dict | None,
    ) -> tuple[DiscussChannelMember, dict]:
        Member = self.env["discuss.channel.member"]
        vals_by_sudo = defaultdict(list)
        channels_by_sudo = defaultdict(list)
        parent_personas = self._get_parent_channel_personas(partners, guests)
        for channel in self:
            existing_members = existing_by_channel[channel]
            actor_holds_parent = bool(
                channel.parent_channel_id and channel.parent_channel_id.self_member_id
            )
            admitted = parent_personas[channel.parent_channel_id.id]
            for partner in partners - existing_members.partner_id:
                as_sudo = actor_holds_parent and ("partner", partner.id) in admitted
                vals_by_sudo[as_sudo].append(
                    {
                        **(create_member_params or {}),
                        "partner_id": partner.id,
                        "channel_id": channel.id,
                    }
                )
                channels_by_sudo[as_sudo].append(channel)
            for guest in guests - existing_members.guest_id:
                as_sudo = actor_holds_parent and ("guest", guest.id) in admitted
                vals_by_sudo[as_sudo].append(
                    {
                        **(create_member_params or {}),
                        "guest_id": guest.id,
                        "channel_id": channel.id,
                    }
                )
                channels_by_sudo[as_sudo].append(channel)
        by_channel = defaultdict(lambda: Member)
        all_created = Member
        for as_sudo, vals in vals_by_sudo.items():
            created = (Member.sudo() if as_sudo else Member).create(vals)
            all_created += created
            for channel, member in zip(channels_by_sudo[as_sudo], created, strict=True):
                by_channel[channel] |= member
        return all_created, by_channel

    def _notify_members_joined(
        self, new_members: DiscussChannelMember, invite_to_rtc_call: bool
    ) -> None:
        channel_data = {}
        for member in new_members:
            channel = member.channel_id
            store = Store(bus_channel=member._bus_channel())
            key = (channel.id, store.target.is_current_user(self.env))
            if key not in channel_data:
                channel_data[key] = Store(bus_channel=member._bus_channel()).add(
                    channel
                )
            store.data = deepcopy(channel_data[key].data)
            store.add(member, "unpin_dt")
            payload = {
                "channel_id": channel.id,
                "invite_to_rtc_call": invite_to_rtc_call,
                "data": store.get_result(),
            }
            if not member.is_self and not self.env.user._is_public():
                payload["invited_by_user_id"] = self.env.user.id
            member._bus_send("discuss.channel/joined", payload)

    def _invite_new_members_to_call(self, new_members_by_channel: dict) -> None:
        for channel in self:
            channel_new_members = new_members_by_channel.get(channel)
            if not channel_new_members:
                continue
            self_member = channel.self_member_id
            if self_member and self_member.sudo().rtc_session_ids:
                self_member.sudo()._rtc_invite_members(
                    member_ids=channel_new_members.ids
                )

    def _post_joined_messages(
        self, new_members: DiscussChannelMember, inviting_partner: ResPartner
    ) -> None:
        self.ensure_one()
        body_template = Markup(
            '<div class="o_mail_notification" data-oe-type="channel-joined">%s</div>'
        )
        notifications = []
        if new_members.filtered("is_self"):
            notifications.append(self.env._("joined the channel"))
        if invited := new_members.filtered(lambda member: not member.is_self):
            list_params = [f"%(member_{member.id})s" for member in invited]
            member_names = html_escape(format_list(self.env, list_params)) % {
                f"member_{member.id}": member._get_html_link(for_persona=True)
                for member in invited
            }
            notifications.append(self.env._("invited %s to the channel", member_names))
        for notification in notifications:
            self.message_post(
                author_id=inviting_partner.id or None,
                body=body_template % notification,
                message_type="notification",
                subtype_xmlid="mail.mt_comment",
            )

    def invite_by_email(self, emails: list[str]) -> None:
        if not self.env.user._is_internal() or not (
            self.env.is_admin() or self.self_member_id
        ):
            raise AccessError(
                self.env._("You don't have access to invite users to this channel.")
            )
        if not self._allow_invite_by_email():
            raise UserError(
                self.env._(
                    "Inviting by email is not allowed for this channel type (%s)."
                )
                % self.channel_type
            )
        if len(emails) > self.MAX_EMAIL_INVITES:
            raise UserError(
                self.env._(
                    "You cannot invite more than %(limit)s addresses at once.",
                    limit=self.MAX_EMAIL_INVITES,
                )
            )
        to_create = self._get_invitation_mail_values(self._get_uninvited_emails(emails))
        if not to_create:
            return
        try:
            self.env["mail.mail"].sudo().create(to_create).send(raise_exception=True)
        except MailDeliveryException as mde:
            error_msg = self.env._(
                "There was an error when trying to deliver your Email, please check your configuration."
            )
            if len(mde.args) == 2 and isinstance(mde.args[1], ConnectionRefusedError):
                error_msg = self.env._(
                    "Could not contact the mail server, please check your outgoing email server configuration."
                )
            raise UserError(error_msg) from mde

    def _get_uninvited_emails(self, emails: list[str]) -> OrderedSet:
        self.ensure_one()
        eligible_emails = OrderedSet(
            norm for email in emails if email and (norm := email_normalize(email))
        )
        member_domain = Domain("channel_id", "=", self.id) & Domain.OR(
            [
                [(field, "=ilike", email)]
                for email in eligible_emails
                for field in ("guest_id.email", "partner_id.email")
            ],
        )
        eligible_emails -= set(
            self.env["discuss.channel.member"]
            .search_fetch(member_domain, ["partner_id", "guest_id"])
            .mapped(lambda m: email_normalize(m.partner_id.email or m.guest_id.email))
        )
        return eligible_emails

    def _get_invitation_mail_values(self, addresses: OrderedSet) -> list[dict]:
        self.ensure_one()
        mail_body = (
            Markup("<p>%s</p>")
            % self.env._(
                "%(user_name)s has invited you to the %(strong_start)s%(channel_name)s%(strong_end)s channel."
            )
            % {
                "user_name": self.env.user.name,
                "channel_name": self.name,
                "strong_start": Markup("<strong>"),
                "strong_end": Markup("</strong>"),
            }
        )
        base_url = self.env["ir.config_parameter"].get_base_url()
        email_from = self.env.user.partner_id.email_formatted
        subject = self.env._("%(author_name)s has invited you to a channel") % {
            "author_name": self.env.user.name
        }
        return [
            {
                "body_html": self.env["ir.qweb"]._render(
                    "mail.discuss_channel_invitation_template",
                    {
                        "base_url": base_url,
                        "channel": self,
                        "email_token": hash_sign(
                            self.env(su=True), "mail.invite_email", addr
                        ),
                        "mail_body": mail_body,
                        "user": self.env.user,
                    },
                    minimal_qcontext=True,
                ),
                "email_from": email_from,
                "email_to": addr,
                "message_type": "user_notification",
                "model": "discuss.channel",
                "res_id": self.id,
                "subject": subject,
            }
            for addr in addresses
        ]

    def _subscribe_users_automatically(self) -> None:
        new_members_to_create = self._subscribe_users_automatically_get_members()
        if not any(new_members_to_create.values()):
            return
        to_create = [
            {"channel_id": channel_id, "partner_id": partner_id}
            for channel_id in new_members_to_create
            for partner_id in new_members_to_create[channel_id]
        ]
        new_members = self.env["discuss.channel.member"].sudo().create(to_create)
        notifications = defaultdict(lambda: self.env["discuss.channel.member"])
        for member in new_members:
            bus_channel = member._bus_channel()
            notifications[bus_channel] |= member
        for bus_channel, members in notifications.items():
            members = members.with_prefetch(new_members.ids)
            Store(bus_channel=bus_channel).add(members.channel_id).add(
                members,
                [
                    Store.One("channel_id", [], as_thread=True),
                    *self.env["discuss.channel.member"]._to_store_persona(),
                    "unpin_dt",
                ],
            ).bus_send()

    def _subscribe_users_automatically_get_members(self) -> dict:
        return {
            channel.id: (
                (
                    channel.group_ids.all_user_ids.partner_id.filtered(
                        lambda p: p.active
                    )
                    - channel.channel_partner_ids
                ).ids
            )
            for channel in self
        }

    def _get_or_create_member_for_self(self) -> DiscussChannelMember:
        self.ensure_one()
        if member := self.self_member_id:
            return member
        if not self.env.user._is_public():
            return self._add_members(users=self.env.user)
        guest = self.env["mail.guest"]._get_guest_from_context()
        if guest:
            return self._add_members(guests=guest)
        return self.env["discuss.channel.member"]

    def _get_or_create_persona_for_channel(
        self,
        guest_name: str,
        timezone: str | None,
        country_code: str | None,
        create_member_params: dict | None = None,
        post_joined_message: bool = True,
    ) -> tuple:
        self.ensure_one()
        guest = self.env["mail.guest"]
        if member := self.self_member_id:
            return member.partner_id, member.guest_id
        if not self.env.user._is_public():
            self._add_members(
                users=self.env.user, post_joined_message=post_joined_message
            )
        else:
            guest = guest._get_or_create_guest(
                guest_name=guest_name, country_code=country_code, timezone=timezone
            )
            self.with_context(guest=guest)._add_members(
                guests=guest,
                create_member_params=create_member_params,
                post_joined_message=post_joined_message,
            )
        return self.env.user.partner_id if not guest else self.env["res.partner"], guest

    @api.model
    def _get_channels_as_member(self) -> Self:
        return self.env["discuss.channel"].search(
            Domain(
                [
                    ("channel_type", "in", ("channel", "group")),
                    ("is_member", "=", True),
                ]
            )
            | Domain(
                [
                    ("channel_type", "not in", ("channel", "group")),
                    (
                        "channel_member_ids",
                        "any",
                        [("is_self", "=", True), ("is_pinned", "=", True)],
                    ),
                ]
            )
        )

    def channel_join(self) -> None:
        self._add_members(users=self.env.user)

    def channel_pin(self, pinned: bool = False) -> None:
        self.ensure_one()
        member = self.self_member_id.filtered(lambda m: m.is_pinned != pinned)
        if member:
            member.write({"unpin_dt": False if pinned else fields.Datetime.now()})
        store = Store(bus_channel=self.self_member_id._bus_channel() or self.env.user)
        if not pinned:
            store.add(self, {"close_chat_window": True})
        else:
            store.add(self)
        store.bus_send()

    def channel_fetched(self) -> None:
        channels = self.filtered(
            lambda c: c.channel_type in self._types_allowing_seen_infos()
        )
        if not channels:
            return
        last_message_id_by_channel_id = {
            message.res_id: message.id for message in channels._get_last_messages()
        }
        if not last_message_id_by_channel_id:
            return
        members = self.env["discuss.channel.member"].search(
            [
                ("channel_id", "in", list(last_message_id_by_channel_id)),
                ("partner_id", "=", self.env.user.partner_id.id),
            ]
        )
        outdated = [
            (member, last_message_id_by_channel_id[member.channel_id.id])
            for member in members
            if member.fetched_message_id.id
            != last_message_id_by_channel_id[member.channel_id.id]
        ]
        if not outdated:
            return
        self.env.cr.execute(
            """
            UPDATE discuss_channel_member member
               SET fetched_message_id = new.last_message_id
              FROM (SELECT * FROM unnest(%s::int[], %s::int[])
                      AS t(member_id, last_message_id)) new
             WHERE member.id IN (
                   SELECT id FROM discuss_channel_member
                    WHERE id = new.member_id
                      FOR NO KEY UPDATE SKIP LOCKED
                   )
         RETURNING member.id, member.fetched_message_id
            """,
            ([member.id for member, _ in outdated], [mid for _, mid in outdated]),
        )
        fetched_by_member_id = dict(self.env.cr.fetchall())
        if not fetched_by_member_id:
            return
        members.invalidate_recordset(["fetched_message_id"])
        for member, last_message_id in outdated:
            if fetched_by_member_id.get(member.id) != last_message_id:
                continue
            member.channel_id._bus_send(
                "discuss.channel.member/fetched",
                {
                    "channel_id": member.channel_id.id,
                    "id": member.id,
                    "last_message_id": last_message_id,
                    "partner_id": self.env.user.partner_id.id,
                },
            )

    def _get_call_notification_tag(self) -> str:
        self.ensure_one()
        return f"call_{self.id}"

    def _rtc_cancel_invitations(self, member_ids: list[int] | None = None) -> None:
        self.ensure_one()
        channel_member_domain = Domain(
            [
                ("channel_id", "=", self.id),
                ("rtc_inviting_session_id", "!=", False),
            ]
        )
        if member_ids:
            channel_member_domain &= Domain("id", "in", member_ids)
        members = self.env["discuss.channel.member"].search(channel_member_domain)
        members.rtc_inviting_session_id = False
        if members:
            Store(bus_channel=self).add(
                self,
                {
                    "invited_member_ids": Store.Many(
                        members,
                        [
                            Store.One("channel_id", [], as_thread=True),
                            *self.env["discuss.channel.member"]._to_store_persona(
                                AVATAR_CARD_FIELDS
                            ),
                        ],
                        mode="DELETE",
                    ),
                },
            ).bus_send()
            devices, private_key, public_key = self._web_push_get_partners_parameters(
                members.partner_id.ids
            )
            if devices:
                self._web_push_send_notification(
                    devices,
                    private_key,
                    public_key,
                    payload={
                        "title": "",
                        "options": {
                            "data": {"type": PUSH_NOTIFICATION_TYPE.CANCEL},
                            "tag": self._get_call_notification_tag(),
                        },
                    },
                )

    def _should_invite_members_to_join_call(self) -> bool:
        self.ensure_one()
        return len(self.rtc_session_ids) == 1 and self.channel_type != "channel"

    @api.model
    def _create_channel(self, name: str, group_id: int | None) -> Self:
        group = self.env["res.groups"].browse(group_id).exists() if group_id else None
        if group_id and not group:
            raise UserError(
                self.env._(
                    "Cannot restrict the channel to group %(group_id)s: no such group.",
                    group_id=group_id,
                )
            )
        new_channel = self.create(
            {
                "channel_type": "channel",
                "group_public_id": group.id if group else False,
                "name": name,
            }
        )
        notification = Markup('<div class="o_mail_notification">%s</div>') % self.env._(
            "created this channel."
        )
        new_channel.message_post(
            body=notification,
            message_type="notification",
            subtype_xmlid="mail.mt_comment",
        )
        return new_channel

    @api.model
    def _create_group(
        self,
        partners_to: list[int],
        default_display_mode: str | Literal[False] = False,
        name: str = "",
    ) -> Self:
        partners_to = OrderedSet(partners_to)
        channel = self.create(
            {
                "channel_member_ids": [
                    Command.create({"partner_id": partner_id})
                    for partner_id in partners_to
                ],
                "channel_type": "group",
                "default_display_mode": default_display_mode,
                "name": name,
            }
        )
        channel._broadcast(channel.channel_member_ids.partner_id.ids)
        return channel

    def _create_sub_channel(
        self, from_message_id: int | None = None, name: str | None = None
    ) -> Self:
        self.ensure_one()
        message = self.env["mail.message"]
        if from_message_id:
            message = self.env["mail.message"].search([("id", "=", from_message_id)])
        if not name:
            name = self.env._("New Thread")
            if message:
                if message._filter_empty():
                    name = self.env._("This message has been removed")
                elif stripped := message.body and message.body.striptags():
                    name = stripped[:30]
        sub_channel = self.create(
            {
                "channel_type": self.channel_type,
                "from_message_id": message.id,
                "name": name,
                "parent_channel_id": self.id,
            }
        )
        sub_channel.add_members(
            partner_ids=(self.env.user.partner_id | message.author_id).ids,
            post_joined_message=False,
        )
        notification = (
            Markup('<div class="o_mail_notification">%s</div>')
            % self.env._(
                "%(user)s started a thread: %(goto)s%(thread_name)s%(goto_end)s."
            )
        ) % {
            "user": self.env.user.display_name,
            "goto": Markup(
                "<a href='#' class='o_channel_redirect' data-oe-id='%s' data-oe-model='discuss.channel'>"
            )
            % sub_channel.id,
            "goto_end": Markup("</a>"),
            "thread_name": sub_channel.name,
        }
        self.message_post(
            body=notification,
            message_type="notification",
            subtype_xmlid="mail.mt_comment",
        )
        return sub_channel

    @api.model
    def _get_or_create_chat(self, partners_to: list[int], pin: bool = True) -> Self:
        partners = (
            self.env["res.partner"]
            .with_context(active_test=False)
            .search([("id", "in", partners_to)])
        ) | self.env.user.partner_id
        if len(partners) > 2:
            raise UserError(
                self.env._(
                    "A chat should not be created with more than 2 persons. Create a group instead."
                )
            )
        self.env.cr.execute(
            SQL(
                "SELECT pg_advisory_xact_lock(hashtextextended('discuss.chat:' || %s, 0))",
                ",".join(str(partner_id) for partner_id in sorted(partners.ids)),
            )
        )
        self.flush_model(["channel_type"])
        self.env["discuss.channel.member"].flush_model(["channel_id", "partner_id"])
        self.env.cr.execute(
            SQL(
                """
            SELECT M.channel_id
            FROM discuss_channel C, discuss_channel_member M
            WHERE M.channel_id = C.id
                AND M.partner_id IN %(partner_ids)s
                AND C.channel_type = 'chat'
                AND NOT EXISTS (
                    SELECT 1
                    FROM discuss_channel_member M2
                    WHERE M2.channel_id = C.id
                        AND M2.partner_id NOT IN %(partner_ids)s
                )
            GROUP BY M.channel_id
            HAVING ARRAY_AGG(DISTINCT M.partner_id ORDER BY M.partner_id) = %(sorted_partner_ids)s::int[]
            LIMIT 1
                """,
                partner_ids=tuple(partners.ids),
                sorted_partner_ids=sorted(partners.ids),
            )
        )
        result = self.env.cr.dictfetchall()
        now = fields.Datetime.now()
        last_interest_dt = now - timedelta(seconds=1)
        if result:
            channel = self.browse(result[0].get("channel_id"))
            if pin:
                channel.self_member_id.write(
                    {"last_interest_dt": last_interest_dt, "unpin_dt": False}
                )
            channel._broadcast(self.env.user.partner_id.ids)
        else:
            channel = self.create(
                {
                    "channel_member_ids": [
                        Command.create(
                            {
                                "last_interest_dt": last_interest_dt,
                                "partner_id": partner.id,
                                "unpin_dt": False
                                if partner == self.env.user.partner_id
                                else now,
                            }
                        )
                        for partner in partners
                    ],
                    "channel_type": "chat",
                    "last_interest_dt": last_interest_dt,
                    "name": ", ".join(partners.mapped("name")),
                }
            )
            channel._broadcast(partners.ids)
        return channel

    def channel_set_custom_name(self, name: str) -> None:
        self.ensure_one()
        self.self_member_id.custom_channel_name = name
        Store(bus_channel=self.self_member_id._bus_channel()).add(
            self.self_member_id,
            "custom_channel_name",
        ).bus_send()

    def channel_rename(self, name: str) -> None:
        self.ensure_one()
        self.write({"name": name})
        body = (
            Markup(
                '<div data-oe-type="channel_rename" class="o_mail_notification">%s</div>'
            )
            % name
        )
        self.message_post(
            body=body, message_type="notification", subtype_xmlid="mail.mt_comment"
        )

    def channel_change_description(self, description: str) -> None:
        self.ensure_one()
        self.write({"description": description})

    @api.readonly
    @api.model
    def get_mention_suggestions(self, search: str, limit: int = 8) -> dict:
        domain = [("name", "ilike", search), ("channel_type", "=", "channel")]
        channels = self.search(domain, limit=limit)
        channel_fields = [
            "name",
            "channel_type",
            Store.One("group_public_id", ["full_name"]),
            Store.One("parent_channel_id", []),
        ]
        store = Store().add(channels, channel_fields)
        return store.get_result()

    def _prefetch_store_members(
        self, target: Store.Target, channels_with_all_members: Self
    ) -> None:
        all_members = (
            self.self_member_id
            | self.invited_member_ids
            | self.sudo().rtc_session_ids.channel_member_id
            | channels_with_all_members.channel_member_ids
            | self.channel_name_member_ids
        )
        all_members.mapped("create_date")
        Store(bus_channel=target.channel, bus_subchannel=target.subchannel).add(
            all_members
        )

    def _to_store_defaults_for_self(self) -> list[StoreFieldSpec]:
        bus_last_id = self.env["bus.bus"].sudo()._bus_last_id()
        return [
            {"fetchChannelInfoState": "fetched"},
            "is_editable",
            "message_needaction_counter",
            {"message_needaction_counter_bus_id": bus_last_id},
            Store.One(
                "self_member_id",
                extra_fields=[
                    "custom_channel_name",
                    "custom_notifications",
                    "last_interest_dt",
                    "message_unread_counter",
                    {"message_unread_counter_bus_id": bus_last_id},
                    "mute_until_dt",
                    "new_message_separator",
                    Store.One("rtc_inviting_session_id", sudo=True),
                    "unpin_dt",
                ],
                only_data=True,
            ),
        ]

    def _to_store_defaults(self, target: Store.Target) -> StoreFieldsInput:
        self.fetch(["is_member", "self_member_id"])
        channels_with_all_members = self.filtered(
            lambda channel: (
                channel.channel_type not in self._lazy_load_members_channel_types()
            ),
        )
        self._prefetch_store_members(target, channels_with_all_members)
        res = [
            Store.Attr("avatar_cache_key", predicate=is_channel_or_group),
            "channel_type",
            "create_uid",
            Store.Many(
                "channel_member_ids",
                only_data=True,
                sort="id",
                predicate=lambda channel: channel in channels_with_all_members,
            ),
            "default_display_mode",
            Store.Attr("description", predicate=is_channel_or_group),
            Store.One("from_message_id", predicate=is_channel_or_group),
            Store.Many("group_ids", [], predicate=is_channel, sudo=True),
            Store.One("group_public_id", ["full_name"], predicate=is_channel),
            Store.Many(
                "invited_member_ids",
                [
                    Store.One("channel_id", [], as_thread=True),
                    *self.env["discuss.channel.member"]._to_store_persona(
                        AVATAR_CARD_FIELDS
                    ),
                ],
                mode="ADD",
            ),
            "last_interest_dt",
            "member_count",
            "name",
            Store.Many(
                "channel_name_member_ids",
                sort="id",
                predicate=lambda c: (
                    c.channel_type in self._member_based_naming_channel_types()
                ),
            ),
            Store.One("parent_channel_id", predicate=is_channel_or_group),
            Store.Many(
                "rtc_session_ids",
                mode="ADD",
                extra_fields=self.sudo().rtc_session_ids._get_fields_store_extra(),
                sudo=True,
            ),
            "uuid",
        ]
        if target.is_current_user(self.env):
            res += self._to_store_defaults_for_self()
        return res

    def _to_store(self, store: Store, fields: list[StoreFieldSpec]) -> None:
        store.add_records_fields(self, fields)

    def _broadcast(self, partner_ids: list[int]) -> None:
        for partner in self.env["res.partner"].browse(partner_ids):
            if user := partner.main_user_id:
                Store(bus_channel=user).add(
                    self.with_user(user).with_context(allowed_company_ids=[]),
                ).bus_send()

    def execute_command_help(self, **kwargs) -> None:
        self.ensure_one()
        if self.channel_type == "channel":
            msg = self.env._(
                "You are in channel %(bold_start)s#%(channel_name)s%(bold_end)s.",
                bold_start=Markup("<b>"),
                bold_end=Markup("</b>"),
                channel_name=self.name,
            )
        elif members := self.channel_member_ids.filtered(lambda m: not m.is_self):
            member_names = html_escape(
                format_list(self.env, [f"%(member_{member.id})s" for member in members])
            ) % {
                f"member_{member.id}": member._get_html_link(for_persona=True)
                for member in members
            }
            msg = self.env._(
                "You are in a private conversation with %(member_names)s.",
                member_names=member_names,
            )
        else:
            msg = self.env._("You are alone in a private conversation.")
        msg += self._execute_command_help_message_extra()
        self.env.user._bus_send_transient_message(self, msg)

    def _execute_command_help_message_extra(self) -> str:
        return self.env._(
            "%(new_line)s"
            "%(new_line)sType %(bold_start)s@username%(bold_end)s to mention someone, and grab their attention."
            "%(new_line)sType %(bold_start)s#channel%(bold_end)s to mention a channel."
            "%(new_line)sType %(bold_start)s/command%(bold_end)s to execute a command."
            "%(new_line)sType %(bold_start)s::shortcut%(bold_end)s to insert a canned response in your message."
            "%(new_line)sType %(bold_start)s:emoji:%(bold_end)s to insert an emoji in your message.",
            bold_start=Markup("<b>"),
            bold_end=Markup("</b>"),
            new_line=Markup("<br>"),
        )

    def execute_command_leave(self, **kwargs) -> None:
        if self.channel_type in self._types_allowing_unfollow():
            self.action_unfollow()
        else:
            self.channel_pin(False)

    def execute_command_who(self, **kwargs) -> None:
        if all_other_members := self.channel_member_ids.filtered(
            lambda m: not m.is_self
        ):
            members = all_other_members[:30]
            list_params = [f"%(member_{member.id})s" for member in members]
            if len(all_other_members) != len(members):
                list_params.append(self.env._("more"))
            else:
                list_params.append(self.env._("you"))
            member_names = html_escape(format_list(self.env, list_params)) % {
                f"member_{member.id}": member._get_html_link(for_persona=True)
                for member in members
            }
            msg = self.env._(
                "Users in this channel: %(members)s.",
                members=member_names,
            )
        else:
            msg = self.env._("You are alone in this channel.")
        self.env.user._bus_send_transient_message(self, msg)

    def _allow_invite_by_email(self) -> bool:
        return self.channel_type == "group" or (
            self.channel_type == "channel" and not self.group_public_id
        )

    def _types_allowing_seen_infos(self) -> list:
        return ["chat", "group"]

    def _types_allowing_unfollow(self) -> list:
        return ["channel", "group"]

    def _member_based_naming_channel_types(self) -> list:
        return ["group"]

    def _lazy_load_members_channel_types(self) -> list:
        return ["channel", "group"]

    def _get_access_action(
        self, access_uid: int | None = None, force_website: bool = False
    ) -> dict:
        self.ensure_one()
        if not self.env.user._is_internal() or force_website:
            return {
                "type": "ir.actions.act_url",
                "url": f"/discuss/channel/{self.id}",
                "target": "self",
                "target_type": "public",
            }
        return {
            "type": "ir.actions.act_url",
            "url": f"/odoo/action-mail.action_discuss?active_id={self.id}",
            "target": "self",
        }
