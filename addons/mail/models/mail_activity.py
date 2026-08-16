import functools
import logging
import typing
from ast import literal_eval
from collections import Counter, defaultdict
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Literal, Self

from dateutil.relativedelta import MO, relativedelta

from odoo import _, api, fields, models
from odoo.api import DomainType, ValuesType
from odoo.exceptions import AccessError, MissingError
from odoo.fields import Domain
from odoo.libs.datetime import all_timezones, timezone
from odoo.tools import SQL, OrderedSet, Query, is_html_empty
from odoo.tools.misc import clean_context, get_lang

from odoo.addons.mail.tools.access_scan import scan_accessible_ids
from odoo.addons.mail.tools.discuss import Store, StoreFieldsInput

if typing.TYPE_CHECKING:
    from .mail_activity_type import MailActivityType
    from .mail_template import MailTemplate
    from .res_partner import ResPartner
    from odoo.addons.base.models.ir_model import IrModel
    from odoo.addons.bus.models.ir_attachment import IrAttachment
    from odoo.addons.bus.models.res_users import ResUsers

_logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=4)
def _today_by_timezone(anchor: datetime) -> tuple:
    days = defaultdict(list)
    for tz_name in all_timezones():
        days[anchor.astimezone(timezone(tz_name)).date()].append(tz_name)
    utc_today = anchor.date()
    return utc_today, [(day, names) for day, names in days.items() if day != utc_today]


def _tz_anchor(moment: datetime) -> datetime:
    return moment.replace(minute=moment.minute // 15 * 15, second=0, microsecond=0)


class MailActivity(models.Model):
    _name = "mail.activity"
    _description = "Activity"
    _order = "date_deadline ASC, id ASC"
    _rec_name = "summary"

    @api.model
    def default_get(self, fields: list[str]) -> ValuesType:
        res = super().default_get(fields)
        if "res_model_id" in fields and res.get("res_model"):
            res["res_model_id"] = self.env["ir.model"]._get(res["res_model"]).id
        return res

    @api.model
    def _default_activity_type(self) -> MailActivityType:
        default_vals = self.default_get(["res_model_id", "res_model"])
        current_model = default_vals.get("res_model")
        if not current_model and default_vals.get("res_model_id"):
            current_model = (
                self.env["ir.model"].sudo().browse(default_vals["res_model_id"]).model
            )
        return self._default_activity_type_for_model(current_model)

    @api.model
    def _default_activity_type_for_model(self, model: str) -> MailActivityType:
        if model:
            return self.env["mail.activity.type"].search(
                ["|", ("res_model", "=", model), ("res_model", "=", False)], limit=1
            )
        return self.env["mail.activity.type"].search(
            [("res_model", "=", False)], limit=1
        )

    res_model_id: IrModel = fields.Many2one(
        "ir.model", "Document Model", index=True, ondelete="cascade", required=False
    )
    res_model = fields.Char(
        "Related Document Model",
        index=True,
        related="res_model_id.model",
        precompute=True,
        store=True,
        readonly=True,
    )
    res_id = fields.Many2oneReference(
        string="Related Document ID", index=True, model_field="res_model"
    )
    res_name = fields.Char(
        "Document Name",
        compute="_compute_res_name",
        compute_sudo=True,
        store=True,
        readonly=True,
    )
    activity_type_id: MailActivityType = fields.Many2one(
        "mail.activity.type",
        string="Activity Type",
        domain="['|', ('res_model', '=', False), ('res_model', '=', res_model)]",
        ondelete="restrict",
        default=_default_activity_type,
    )
    activity_category = fields.Selection(
        related="activity_type_id.category", readonly=True
    )
    activity_decoration = fields.Selection(
        related="activity_type_id.decoration_type", readonly=True
    )
    icon = fields.Char("Icon", related="activity_type_id.icon", readonly=True)
    summary = fields.Char("Summary")
    note = fields.Html("Note", sanitize_style=True)
    date_deadline = fields.Date(
        "Due Date", index=True, required=True, default=fields.Date.context_today
    )
    date_done = fields.Date("Done Date", compute="_compute_date_done", store=True)
    feedback = fields.Text("Feedback")
    automated = fields.Boolean(
        "Automated activity",
        readonly=True,
        help="Indicates this activity has been created automatically and not by any user.",
    )
    attachment_ids: IrAttachment = fields.Many2many(
        "ir.attachment",
        "activity_attachment_rel",
        "activity_id",
        "attachment_id",
        string="Attachments",
        bypass_search_access=True,
    )
    user_id: ResUsers = fields.Many2one(
        "res.users", "Assigned to", index=True, required=False, ondelete="cascade"
    )
    user_tz = fields.Selection(string="Timezone", related="user_id.tz", store=True)
    state = fields.Selection(
        [
            ("overdue", "Overdue"),
            ("today", "Today"),
            ("planned", "Planned"),
            ("done", "Done"),
        ],
        "State",
        compute="_compute_state",
    )
    recommended_activity_type_id: MailActivityType = fields.Many2one(
        "mail.activity.type", string="Recommended Activity Type"
    )
    previous_activity_type_id: MailActivityType = fields.Many2one(
        "mail.activity.type", string="Previous Activity Type", readonly=True
    )
    has_recommended_activities = fields.Boolean(
        "Next activities available", compute="_compute_has_recommended_activities"
    )
    mail_template_ids: MailTemplate = fields.Many2many(
        related="activity_type_id.mail_template_ids", readonly=True
    )
    chaining_type = fields.Selection(
        related="activity_type_id.chaining_type", readonly=True
    )
    can_write = fields.Boolean(compute="_compute_can_write")
    active = fields.Boolean(default=True)

    _SEARCH_ACCESS_CHUNK_MIN = 80
    _SEARCH_ACCESS_CHUNK_MAX = 8192

    _check_res_id_is_set_if_model = models.Constraint(
        """CHECK(
            (COALESCE(res_model, '') <> '' AND (res_id IS NOT NULL AND res_id != 0)) OR
            (COALESCE(res_model, '') = '' AND (res_id IS NULL OR res_id = 0))
        )""",
        "Activities have to be linked to records with a not null res_id.",
    )
    _check_user_id_is_set_if_model = models.Constraint(
        """CHECK(
            (COALESCE(res_model, '') <> '' OR user_id IS NOT NULL)
        )""",
        "Activities must be assigned if not attached to a document.",
    )

    @api.depends("previous_activity_type_id.suggested_next_type_ids")
    @api.onchange("previous_activity_type_id")
    def _compute_has_recommended_activities(self) -> None:
        for record in self:
            record.has_recommended_activities = bool(
                record.previous_activity_type_id.suggested_next_type_ids
            )

    @api.onchange("previous_activity_type_id")
    def _onchange_previous_activity_type_id(self) -> None:
        for record in self:
            if record.previous_activity_type_id.triggered_next_type_id:
                record.activity_type_id = (
                    record.previous_activity_type_id.triggered_next_type_id
                )

    @api.depends("active")
    def _compute_date_done(self) -> None:
        unarchived = self.filtered("active")
        unarchived.date_done = False
        toupdate = (self - unarchived).filtered(lambda act: not act.date_done)
        for tz, activities in toupdate.grouped("user_tz").items():
            activities.date_done = self._compute_today_for_tz(tz)

    @api.depends("res_model", "res_id")
    def _compute_res_name(self) -> None:
        linked = self._document_backed()
        (self - linked).res_name = False
        if not linked:
            return
        for model, activities in linked.grouped("res_model").items():
            records = self.env[model].browse(activities.mapped("res_id"))
            try:
                name_by_id = dict(records.mapped(lambda r: (r.id, r.display_name)))
            except MissingError:
                records = records.exists()
                name_by_id = dict(records.mapped(lambda r: (r.id, r.display_name)))
            for activity in activities:
                activity.res_name = name_by_id.get(activity.res_id, False)

    @api.depends("active", "date_deadline", "user_tz")
    def _compute_state(self) -> None:
        self.state = False
        dated = self.filtered("date_deadline")
        done = dated.filtered(lambda activity: not activity.active)
        done.state = "done"
        for tz, activities in (dated - done).grouped("user_tz").items():
            today = self._compute_today_for_tz(tz)
            for activity in activities:
                activity.state = self._state_from(activity.date_deadline, today)

    @api.model
    def _state_from(self, date_deadline: date, today: date) -> str:
        diff = fields.Date.from_string(date_deadline) - today
        if diff.days == 0:
            return "today"
        return "overdue" if diff.days < 0 else "planned"

    @api.model
    def _compute_today_for_tz(self, tz: str | Literal[False] = False) -> date:
        today_utc = datetime.now(UTC)
        if not tz:
            return today_utc.date()
        today_tz = today_utc.astimezone(timezone(tz))
        return date(year=today_tz.year, month=today_tz.month, day=today_tz.day)

    @api.model
    def _sql_today(self, alias: str = "mail_activity") -> SQL:
        utc_today, other_days = _today_by_timezone(_tz_anchor(datetime.now(UTC)))
        if not other_days:
            return SQL("%s::date", utc_today)
        user_tz = SQL("%s::text", SQL.identifier(alias, "user_tz"))
        branches = SQL(" ").join(
            SQL("WHEN %s = ANY(%s::text[]) THEN %s::date", user_tz, names, day)
            for day, names in other_days
        )
        return SQL("(CASE %s ELSE %s::date END)", branches, utc_today)

    @api.model
    def _sql_state(self, alias: str = "mail_activity") -> SQL:
        return SQL(
            "SIGN(%s - %s)::int",
            SQL.identifier(alias, "date_deadline"),
            self._sql_today(alias),
        )

    @api.model
    def _sql_first_activity_ids(
        self, res_model: str, user_id: int | None = None
    ) -> SQL:
        condition = SQL(
            "res_model = %s AND active = true",
            res_model,
        )
        if user_id is not None:
            condition = SQL("%s AND user_id = %s", condition, user_id)
        return SQL(
            "(SELECT DISTINCT ON (res_id) id FROM mail_activity WHERE %s"
            " ORDER BY res_id, date_deadline, id)",
            condition,
        )

    @api.model
    def _compute_state_from_date(
        self, date_deadline: date, tz: str | Literal[False] = False
    ) -> str:
        return self._state_from(date_deadline, self._compute_today_for_tz(tz))

    def _filtered_todo(self) -> Self:
        candidates = self.filtered(
            lambda activity: activity.active and activity.user_id
        )
        todo = self.browse()
        for tz, activities in candidates.grouped("user_tz").items():
            today = self._compute_today_for_tz(tz)
            todo |= activities.filtered(
                lambda activity, day=today: activity.date_deadline <= day
            )
        return todo

    def _todo_key(self) -> tuple:
        self.ensure_one()
        return (
            (self.res_model, self.res_id) if self.res_model else (self._name, self.id)
        )

    def _todo_keys(self, within: set[tuple[str, int]] | None = None) -> dict:
        result = defaultdict(set)
        for activity in self._filtered_todo():
            key = activity._todo_key()
            if within is None or key in within:
                result[activity.user_id].add(key)
        return result

    def _todo_keys_elsewhere(self, keys: set[tuple[str, int]]) -> dict:
        if not keys:
            return {}
        documents = Domain.FALSE
        modelless_ids = []
        by_model = defaultdict(list)
        for res_model, res_id in keys:
            by_model[res_model].append(res_id)
            if res_model == self._name:
                modelless_ids.append(res_id)
        for res_model, res_ids in by_model.items():
            documents |= Domain("res_model", "=", res_model) & Domain(
                "res_id", "in", res_ids
            )
        if modelless_ids:
            documents |= Domain("id", "in", modelless_ids) & Domain(
                "res_model", "=", False
            )
        domain = (
            Domain("active", "=", True) & Domain("user_id", "!=", False) & documents
        )
        if self.ids:
            domain &= Domain("id", "not in", self.ids)
        return self.sudo().search(domain)._todo_keys(within=keys)

    @staticmethod
    def _merged_todo_keys(*mappings) -> dict:
        return {
            user: set().union(*(m.get(user, ()) for m in mappings))
            for user in set().union(*(m.keys() for m in mappings))
        }

    def _notify_todo_count_change(self, before: dict, after: dict) -> None:
        for user in before.keys() | after.keys():
            count_diff = len(after.get(user, ())) - len(before.get(user, ()))
            if count_diff > 0:
                user._bus_send(
                    "mail.activity/updated",
                    {"activity_created": True, "count_diff": count_diff},
                )
            elif count_diff < 0:
                user._bus_send(
                    "mail.activity/updated",
                    {"activity_deleted": True, "count_diff": count_diff},
                )

    @api.depends("res_model", "res_id", "user_id")
    @api.depends_context("uid")
    def _compute_can_write(self) -> None:
        valid_ids = set(self._filtered_access("write")._ids)
        for record in self:
            record.can_write = record.id in valid_ids

    @api.onchange("activity_type_id")
    def _onchange_activity_type_id(self) -> None:
        if self.activity_type_id:
            if self.activity_type_id.summary:
                self.summary = self.activity_type_id.summary
            self.date_deadline = self.activity_type_id._get_date_deadline()
            self.user_id = self.activity_type_id.default_user_id or self.env.user
            if self.activity_type_id.default_note:
                self.note = self.activity_type_id.default_note

    @api.onchange("recommended_activity_type_id")
    def _onchange_recommended_activity_type_id(self) -> None:
        if self.recommended_activity_type_id:
            self.activity_type_id = self.recommended_activity_type_id

    def _check_access(self, operation: str) -> tuple | None:
        result = super()._check_access(operation)
        if not self:
            return result

        if operation == "read":
            activities = self - result[0] if result else self
            activities -= activities.sudo().filtered_domain(
                [("user_id", "=", self.env.uid)]
            )
        elif operation == "create":
            activities = self - result[0] if result else self
        elif operation in ("write", "unlink"):
            if self.browse()._check_access(operation):
                return result
            activities = result[0] if result else self.browse()
            result = None
        else:
            raise ValueError(f"Unexpected operation {operation!r}")

        if not activities:
            return result

        model_docid_actids = defaultdict(lambda: defaultdict(list))
        forbidden_ids = []
        for activity in activities.sudo():
            if activity.res_model and activity.res_model in self.env:
                model_docid_actids[activity.res_model][activity.res_id].append(
                    activity.id
                )
            elif activity.user_id.id != self.env.uid:
                forbidden_ids.append(activity.id)

        for doc_model, docid_actids in model_docid_actids.items():
            allowed = self.env["mail.message"]._filter_records_for_message_operation(
                doc_model, docid_actids, operation
            )
            for document_id in [
                doc_id for doc_id in docid_actids if doc_id not in allowed.ids
            ]:
                forbidden_ids.extend(docid_actids[document_id])

        if forbidden_ids:
            forbidden = self.browse(forbidden_ids)
            if result:
                result = (result[0] + forbidden, result[1])
            else:
                result = (forbidden, lambda: forbidden._make_access_error(operation))

        return result

    def _make_access_error(self, operation: str) -> AccessError:
        return AccessError(
            _(
                "The requested operation cannot be completed due to security restrictions. "
                "Please contact your system administrator.\n\n"
                "(Document type: %(type)s, Operation: %(operation)s)\n\n"
                "Records: %(records)s, User: %(user)s",
                type=self._description,
                operation=operation,
                records=self.ids[:6],
                user=self.env.uid,
            )
        )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        activities = super().create(vals_list)

        if any(user != self.env.user for user in activities.user_id):
            user_partners = activities.user_id.partner_id
            readable_user_partners = user_partners._filtered_access("read")
        else:
            readable_user_partners = self.env.user.partner_id

        if self.env.context.get("mail_activity_quick_update"):
            activities_to_notify = self.browse()
        else:
            activities_to_notify = activities.filtered(
                lambda act: act.user_id and act.user_id != self.env.user
            )
        if activities_to_notify:
            to_sudo = activities_to_notify.filtered(
                lambda act: act.user_id.partner_id not in readable_user_partners
            )
            other = activities_to_notify - to_sudo
            to_sudo.sudo().action_notify()
            other.action_notify()

        activities._subscribe_assignees(readable_user_partners)

        mine = activities._todo_keys()
        if mine:
            keys = set().union(*mine.values())
            elsewhere = activities._todo_keys_elsewhere(keys)
            self._notify_todo_count_change(
                elsewhere, self._merged_todo_keys(elsewhere, mine)
            )
        return activities

    def _filtered_postable(self) -> Self:
        allowed = self.browse()
        for model, res_ids in self._records_by_model().items():
            ok = self.env["mail.message"]._filter_records_for_message_operation(
                model, res_ids, "create"
            )
            allowed |= self.filtered(
                lambda act, m=model, ids=set(ok._ids): (
                    act.res_model == m and act.res_id in ids
                )
            )
        return allowed

    def _subscribe_assignees(self, readable_user_partners: ResPartner) -> None:
        for model, activities in self._thread_backed().grouped("res_model").items():
            per_user = defaultdict(set)
            for activity in activities.filtered("user_id"):
                per_user[activity.user_id].add(activity.res_id)
            for user, res_ids in per_user.items():
                pids = (
                    user.partner_id.ids
                    if user.partner_id in readable_user_partners
                    else user.sudo().partner_id.ids
                )
                self.env[model].browse(res_ids)._message_subscribe(partner_ids=pids)

    def _prospective_todo_keys(self, vals: ValuesType) -> set:
        res_model = None
        if "res_model_id" in vals:
            res_model = (
                self.env["ir.model"].sudo().browse(vals["res_model_id"]).model
                if vals["res_model_id"]
                else False
            )
        keys = set()
        for activity in self:
            model = activity.res_model if res_model is None else res_model
            res_id = vals.get("res_id", activity.res_id)
            keys.add((model, res_id) if model else (self._name, activity.id))
        return keys

    def write(self, vals: ValuesType) -> Literal[True]:
        moves_count = {
            "date_deadline",
            "active",
            "user_id",
            "res_id",
            "res_model_id",
        } & vals.keys()
        keys = elsewhere = mine_before = None
        if moves_count:
            keys = {activity._todo_key() for activity in self}
            keys |= self._prospective_todo_keys(vals)
            elsewhere = self._todo_keys_elsewhere(keys)
            mine_before = self._todo_keys(within=keys)

        reassigned = self.browse()
        if vals.get("user_id"):
            reassigned = self.filtered(
                lambda activity: activity.user_id.id != vals["user_id"]
            )
        moved = self.browse()
        if "res_id" in vals or "res_model_id" in vals:
            moved = self.filtered("user_id")

        res = super().write(vals)

        if (
            reassigned
            and vals["user_id"] != self.env.uid
            and not self.env.context.get("mail_activity_quick_update")
        ):
            reassigned.action_notify()
        if to_subscribe := (reassigned | moved)._filtered_postable():
            partners = to_subscribe.user_id.partner_id
            to_subscribe._subscribe_assignees(partners._filtered_access("read"))

        if moves_count:
            self._notify_todo_count_change(
                self._merged_todo_keys(elsewhere, mine_before),
                self._merged_todo_keys(elsewhere, self._todo_keys(within=keys)),
            )

        return res

    def unlink(self) -> Literal[True]:
        mine = self._todo_keys()
        if not mine:
            return super().unlink()
        keys = set().union(*mine.values())
        elsewhere = self._todo_keys_elsewhere(keys)
        before = self._merged_todo_keys(elsewhere, mine)
        res = super().unlink()
        self._notify_todo_count_change(before, elsewhere)
        return res

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

        fnames = ("id", "res_model", "res_id", "user_id")

        def fetch(query: Query) -> list[tuple]:
            return self.env.execute_query(
                query.select(
                    *[self._field_to_sql(self._table, fname) for fname in fnames]
                )
            )

        def allowed(rows: list[tuple]) -> list[int]:
            model_ids = defaultdict(set)
            for __, res_model, res_id, user_id in rows:
                if user_id != self.env.uid and res_model and res_model in self.env:
                    model_ids[res_model].add(res_id)

            readable = {
                res_model: set(
                    self.env["mail.message"]
                    ._filter_records_for_message_operation(res_model, res_ids, "read")
                    ._ids
                )
                for res_model, res_ids in model_ids.items()
            }
            return [
                id_
                for id_, res_model, res_id, user_id in rows
                if user_id == self.env.uid or res_id in readable.get(res_model, ())
            ]

        ids = scan_accessible_ids(
            self,
            domain,
            offset,
            limit,
            order,
            super()._search,
            fetch=fetch,
            allowed=allowed,
            chunk_min=self._SEARCH_ACCESS_CHUNK_MIN,
            chunk_max=self._SEARCH_ACCESS_CHUNK_MAX,
            **kwargs,
        )
        return self.browse(ids)._as_query(bool(order))

    @api.depends("summary", "activity_type_id")
    def _compute_display_name(self) -> None:
        for record in self:
            name = record.summary or record.activity_type_id.display_name
            record.display_name = name

    def action_notify(self) -> None:
        notifiable = self._thread_backed().filtered("user_id")
        for model, activities in notifiable.grouped("res_model").items():
            records_sudo = self.env[model].sudo().browse(activities.mapped("res_id"))
            existing = records_sudo.exists()
            if not existing:
                continue
            existing_ids = set(existing._ids)
            descriptions = {}
            batches = {}

            for activity in activities:
                if activity.res_id not in existing_ids:
                    continue
                lang = activity.user_id.lang or False
                localized = activity.with_context(lang=lang) if lang else activity
                if lang not in descriptions:
                    descriptions[lang] = (
                        localized.env["ir.model"]._get(model).display_name
                    )
                model_description = descriptions[lang]
                key = (
                    activity.user_id,
                    lang,
                    activity.activity_type_id,
                    activity.date_deadline,
                )
                if key not in batches:
                    batches[key] = {
                        "model_description": model_description,
                        "subtitles": [
                            _(
                                "Activity: %s",
                                localized.activity_type_id.name or _("Todo"),
                            ),
                            _(
                                "Deadline: %s",
                                localized.date_deadline.strftime(
                                    get_lang(localized.env).date_format
                                ),
                            ),
                        ],
                        "entries": [],
                    }
                batches[key]["entries"].append(
                    (
                        activity.res_id,
                        localized.env["ir.qweb"]._render(
                            "mail.message_activity_assigned",
                            {
                                "activity": localized,
                                "model_description": model_description,
                                "is_html_empty": is_html_empty,
                            },
                            minimal_qcontext=True,
                        ),
                        _(
                            '"%(activity_name)s: %(summary)s" assigned to you',
                            activity_name=localized.res_name,
                            summary=localized.summary
                            or localized.activity_type_id.name
                            or "",
                        ),
                    )
                )

            for (user, __lang, __type_name, __deadline), batch in batches.items():
                entries = batch["entries"]
                while entries:
                    bodies, subjects, deferred = {}, {}, []
                    for res_id, body, subject in entries:
                        if res_id in bodies:
                            deferred.append((res_id, body, subject))
                            continue
                        bodies[res_id] = body
                        subjects[res_id] = subject
                    self.env[model].browse(list(bodies))._message_notify_batch(
                        bodies,
                        subjects=subjects,
                        partner_ids=user.partner_id.ids,
                        model_description=batch["model_description"],
                        email_layout_xmlid="mail.mail_notification_layout",
                        subtitles=batch["subtitles"],
                    )
                    entries = deferred

    def action_done(self) -> dict | Literal[False]:
        return self.filtered(lambda r: r.active).action_feedback()

    def action_done_redirect_to_other(self) -> dict:
        self.action_done()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "mail.mail_activity_without_access_action"
        )
        action_context = literal_eval(action.get("context", "{}"))
        if self.env.context.get("active_model") == "mail.activity":
            active_ids = self.env.context.get("active_ids", [])
        else:
            activity_groups = self.env["res.users"]._get_activity_groups()
            activity_model_id = self.env["ir.model"]._get_id("mail.activity")
            active_ids = next(
                (
                    g["activity_ids"]
                    for g in activity_groups
                    if g["id"] == activity_model_id
                ),
                [],
            )
        action["context"] = {
            **action_context,
            "active_ids": active_ids,
            "active_model": "mail.activity",
        }
        return action

    def action_feedback(
        self,
        feedback: str | Literal[False] = False,
        attachment_ids: list[int] | None = None,
    ) -> int | Literal[False]:
        messages, _next_activities = self.with_context(
            clean_context(self.env.context)
        )._action_done(feedback=feedback, attachment_ids=attachment_ids)
        return messages[0].id if messages else False

    def action_feedback_schedule_next(
        self,
        feedback: str | Literal[False] = False,
        attachment_ids: list[int] | None = None,
    ) -> dict | Literal[False]:
        self.ensure_one()
        ctx = dict(
            clean_context(self.env.context),
            default_previous_activity_type_id=self.activity_type_id.id,
            activity_previous_deadline=self.date_deadline,
            default_res_id=self.res_id,
            default_res_model=self.res_model,
        )
        _messages, next_activities = self._action_done(
            feedback=feedback, attachment_ids=attachment_ids
        )
        if next_activities:
            return False
        return {
            "name": _("Schedule an Activity"),
            "context": ctx,
            "view_mode": "form",
            "res_model": "mail.activity",
            "views": [(False, "form")],
            "type": "ir.actions.act_window",
            "target": "new",
        }

    def _action_done(
        self,
        feedback: str | Literal[False] = False,
        attachment_ids: list[int] | None = None,
    ) -> tuple:
        self = self.filtered("active")
        messages = self.env["mail.message"]
        next_activities_values = []
        if not self:
            return messages, self.browse()

        activity_attachments = (
            self.env["ir.attachment"]
            .sudo()
            .search_fetch(
                [
                    ("res_model", "=", self._name),
                    ("res_id", "in", self.ids),
                ],
                ["res_id"],
            )
            .grouped("res_id")
        )
        attachments_to_remove = self.env["ir.attachment"]
        activities_to_remove = self.browse()

        for (
            model,
            activities,
            res_ids,
        ) in self._thread_backed()._activities_with_records():
            records_sudo = self.env[model].sudo().browse(res_ids)
            existing_ids = set(records_sudo.exists()._ids)
            for record_sudo, activity in zip(records_sudo, activities, strict=True):
                if record_sudo.id in existing_ids:
                    if activity.chaining_type == "trigger":
                        vals = activity.with_context(
                            activity_previous_deadline=activity.date_deadline
                        )._prepare_next_activity_values()
                        next_activities_values.append(vals)

                    activity_message = record_sudo.message_post_with_source(
                        "mail.message_activity_done",
                        attachment_ids=attachment_ids,
                        author_id=self.env.user.partner_id.id,
                        render_values={
                            "activity": activity,
                            "feedback": feedback,
                            "display_assignee": activity.user_id != self.env.user,
                        },
                        mail_activity_type_id=activity.activity_type_id.id,
                        subtype_xmlid="mail.mt_activities",
                    )
                else:
                    activity_message = self.env["mail.message"]
                    activities_to_remove += activity
                if attachment_ids:
                    activity.attachment_ids = attachment_ids

                message_attachments = activity_attachments.get(activity.id)
                if message_attachments and activity_message:
                    message_attachments.write(
                        {
                            "res_id": activity_message.id,
                            "res_model": activity_message._name,
                        }
                    )
                    activity_message.attachment_ids = message_attachments
                elif message_attachments:
                    attachments_to_remove += message_attachments
                messages += activity_message

        next_activities = self.env["mail.activity"]
        if next_activities_values:
            next_activities = self.env["mail.activity"].create(next_activities_values)

        if attachments_to_remove:
            attachments_to_remove.unlink()
        if activities_to_remove:
            activities_to_remove.unlink()

        done = self - activities_to_remove
        done.write({"active": False, **({"feedback": feedback} if feedback else {})})
        return messages, next_activities

    @api.readonly
    def action_close_dialog(self) -> dict:
        return {"type": "ir.actions.act_window_close"}

    @api.readonly
    def action_open_document(self) -> dict:
        self.ensure_one()
        if not self.res_model:
            view_id = self.env.ref("mail.mail_activity_view_form_popup").id
            return {
                "res_id": self.id,
                "type": "ir.actions.act_window",
                "view_mode": "form",
                "res_model": "mail.activity",
                "view_id": view_id,
                "views": [(view_id, "form")],
                "target": "new",
            }
        if self.res_model not in self.env or not self.env[self.res_model].browse(
            self.res_id
        ).has_access("read"):
            return {
                "res_id": self.id,
                "res_model": "mail.activity",
                "target": "current",
                "type": "ir.actions.act_window",
                "view_mode": "form",
                "views": [
                    (
                        self.env.ref(
                            "mail.mail_activity_view_form_without_record_access"
                        ).id,
                        "form",
                    )
                ],
            }
        return {
            "res_id": self.res_id,
            "res_model": self.res_model,
            "target": "current",
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "views": [(False, "form")],
        }

    def _action_reschedule_from_today(
        self, offset: timedelta | relativedelta | None = None
    ) -> None:
        for tz, activities in self.filtered("active").grouped("user_tz").items():
            today = self._compute_today_for_tz(tz)
            activities.date_deadline = today + offset if offset else today

    def action_reschedule_today(self) -> None:
        self._action_reschedule_from_today()

    def action_reschedule_tomorrow(self) -> None:
        self._action_reschedule_from_today(timedelta(days=1))

    def action_reschedule_nextweek(self) -> None:
        self._action_reschedule_from_today(relativedelta(weeks=1, weekday=MO(-1)))

    def action_cancel(self) -> None:
        self.filtered("active").unlink()

    @api.readonly
    def activity_format(self) -> dict:
        return Store().add(self).get_result()

    def _to_store_defaults(self, target: Store.Target) -> StoreFieldsInput:
        return [
            "activity_category",
            Store.One("activity_type_id", "name"),
            "can_write",
            "chaining_type",
            "create_date",
            Store.One("create_uid", Store.One("partner_id", "name"), sudo=True),
            "date_deadline",
            "date_done",
            "display_name",
            "icon",
            "note",
            "res_id",
            "res_model",
            "state",
            "summary",
            Store.One(
                "user_id", Store.One("partner_id", ["name", "avatar_128"]), sudo=True
            ),
            Store.Many("attachment_ids", ["name"]),
            Store.Many("mail_template_ids", ["name"]),
        ]

    @api.readonly
    @api.model
    def get_activity_data(
        self,
        res_model: str,
        domain: DomainType,
        limit: int | None = None,
        offset: int = 0,
        fetch_done: bool = False,
    ) -> dict:
        all_ongoing, all_completed = self._get_activity_data_activities(
            res_model, domain, limit, offset, fetch_done
        )
        grouped_activities = self._get_activity_data_cells(
            res_model, all_ongoing, all_completed, bool(domain or limit or offset)
        )
        return {
            "activity_res_ids": self._get_activity_data_order(grouped_activities),
            "activity_types": [
                {
                    "id": activity_type.id,
                    "name": activity_type.name,
                    "template_ids": [
                        {"id": mail_template_id.id, "name": mail_template_id.name}
                        for mail_template_id in activity_type.mail_template_ids
                    ],
                }
                for activity_type in self.env["mail.activity.type"].search(
                    [("res_model", "in", (res_model, False))]
                )
            ],
            "grouped_activities": grouped_activities,
        }

    @api.model
    def _get_activity_data_activities(
        self,
        res_model: str,
        domain: DomainType,
        limit: int | None,
        offset: int,
        fetch_done: bool,
    ) -> tuple:
        DocModel = self.env[res_model]
        activity_domain = [("res_model", "=", res_model)]
        if domain or limit or offset:
            activity_domain.append(
                (
                    "res_id",
                    "in",
                    DocModel._search(domain or [], offset, limit, DocModel._order),
                )
            )
        all_activities = self.with_context(active_test=not fetch_done).search(
            activity_domain, order="date_done DESC, date_deadline ASC"
        )
        return all_activities.filtered("active"), all_activities.filtered(
            lambda act: not act.active
        )

    @api.model
    def _get_activity_data_cells(
        self,
        res_model: str,
        all_ongoing: MailActivity,
        all_completed: MailActivity,
        is_filtered: bool,
    ) -> dict:
        attachments_by_id = {}
        if attachment_ids := all_completed.attachment_ids.ids:
            attachments_by_id = {
                a["id"]: a
                for a in self.env["ir.attachment"].search_read(
                    [["id", "in", attachment_ids]], ["create_date", "name"]
                )
            }

        def by_cell(activities: MailActivity) -> dict:
            return activities.grouped(lambda a: (a.res_id, a.activity_type_id))

        grouped_ongoing = by_cell(all_ongoing)
        grouped_completed = by_cell(all_completed)

        cells = grouped_ongoing.keys() | grouped_completed.keys()
        if not is_filtered:
            readable = set(
                self.env[res_model].search([("id", "in", [c[0] for c in cells])]).ids
            )
            cells = {cell for cell in cells if cell[0] in readable}

        grouped_activities = defaultdict(dict)
        for cell in cells:
            res_id, activity_type = cell
            ongoing = grouped_ongoing.get(cell, self.browse())
            completed = grouped_completed.get(cell, self.browse())
            activities = ongoing | completed

            date_done = completed and completed[0].date_done
            date_deadline = ongoing and ongoing[0].date_deadline

            cell_data = {
                "count_by_state": dict(
                    Counter(
                        self._compute_state_from_date(act.date_deadline, act.user_tz)
                        if act.active
                        else "done"
                        for act in activities
                    )
                ),
                "ids": activities.ids,
                "reporting_date": (ongoing and date_deadline) or date_done or None,
                "state": self._compute_state_from_date(
                    date_deadline, ongoing[0].user_tz
                )
                if ongoing
                else "done",
                "user_assigned_ids": ongoing.user_id.ids,
                "summaries": [act.summary or "" for act in activities],
            }
            attachments = [
                attachment
                for attach in completed.attachment_ids
                if (attachment := attachments_by_id.get(attach.id))
            ]
            if attachments:
                most_recent = max(
                    attachments, key=lambda a: (a["create_date"], a["id"])
                )
                cell_data["attachments_info"] = {
                    "most_recent_id": most_recent["id"],
                    "most_recent_name": most_recent["name"],
                    "count": len(attachments),
                }
            grouped_activities[res_id][activity_type.id] = cell_data
        return grouped_activities

    @api.model
    def _get_activity_data_order(self, grouped_activities: dict) -> list[int]:
        deadline_by_res_id = {}
        done_by_res_id = {}
        for res_id, cells in grouped_activities.items():
            for cell in cells.values():
                date = cell["reporting_date"]
                if not date:
                    continue
                if cell["state"] == "done":
                    previous = done_by_res_id.get(res_id)
                    if previous is None or date > previous:
                        done_by_res_id[res_id] = date
                else:
                    previous = deadline_by_res_id.get(res_id)
                    if previous is None or date < previous:
                        deadline_by_res_id[res_id] = date
        ongoing_res_ids = sorted(deadline_by_res_id, key=deadline_by_res_id.get)
        completed_res_ids = [
            res_id
            for res_id in sorted(done_by_res_id, key=done_by_res_id.get, reverse=True)
            if res_id not in deadline_by_res_id
        ]
        return ongoing_res_ids + completed_res_ids

    def _document_backed(self) -> Self:
        return self.filtered(
            lambda act: act.res_model and act.res_id and act.res_model in self.env
        )

    def _records_by_model(self) -> dict:
        by_model = defaultdict(OrderedSet)
        for activity in self._document_backed():
            by_model[activity.res_model].add(activity.res_id)
        return {model: list(res_ids) for model, res_ids in by_model.items()}

    def _thread_backed(self) -> Self:
        thread = self.pool["mail.thread"]
        return self._document_backed().filtered(
            lambda act: isinstance(self.env[act.res_model], thread)
        )

    def _activities_with_records(self) -> Iterator[tuple[str, Self, list[int]]]:
        for model, activities in self._document_backed().grouped("res_model").items():
            yield model, activities, activities.mapped("res_id")

    def _prepare_next_activity_values(self) -> dict:
        self.ensure_one()
        vals = self.default_get(list(self._fields))

        vals.update(
            {
                "previous_activity_type_id": self.activity_type_id.id,
                "res_id": self.res_id,
                "res_model": self.res_model,
                "res_model_id": self.env["ir.model"]._get(self.res_model).id
                if self.res_model
                else False,
            }
        )
        virtual_activity = self.new(vals)
        virtual_activity._onchange_previous_activity_type_id()
        virtual_activity._onchange_activity_type_id()
        return virtual_activity._convert_to_write(virtual_activity._cache)

    _GC_BATCH = 10_000

    def _gc_retention_years(self, parameter: str) -> int:
        years = self.env["ir.config_parameter"]._get_int_param(parameter, 0)
        if years < 0:
            _logger.warning(
                "The ir.config_parameter %r is set to a negative number which is "
                "invalid. Skipping gc routine.",
                parameter,
            )
            return 0
        if years == 0:
            _logger.debug("%r missing or 0; skipping gc routine.", parameter)
        return years

    @api.autovacuum
    def _gc_delete_old_overdue_activities(self) -> tuple:
        years = self._gc_retention_years("mail.activity.gc.delete_overdue_years")
        if not years:
            return 0, False
        threshold = fields.Date.today() - relativedelta(years=years)
        overdue = self.search([("date_deadline", "<", threshold)], limit=self._GC_BATCH)
        removed = len(overdue)
        overdue.unlink()
        return removed, removed == self._GC_BATCH

    @api.autovacuum
    def _gc_delete_old_done_activities(self) -> tuple:
        years = self._gc_retention_years("mail.activity.gc.delete_done_years")
        if not years:
            return 0, False
        threshold = fields.Date.today() - relativedelta(years=years)
        done = self.with_context(active_test=False).search(
            [("active", "=", False), ("date_done", "<", threshold)],
            limit=self._GC_BATCH,
        )
        removed = len(done)
        done.unlink()
        return removed, removed == self._GC_BATCH
