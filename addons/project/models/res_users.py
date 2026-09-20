from collections import defaultdict
from typing import Self

from odoo import api, models
from odoo.api import ValuesType
from odoo.libs.intervals import Intervals

from ..tools import debug_log as dbg


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        res = super().create(vals_list)
        self._onboard_users_into_project(res)
        return res

    @dbg.timed
    def _onboard_users_into_project(self, users: Self) -> Self | None:
        if internal_users := users.filtered(lambda u: not u.share):
            TriageSudo = self.env["project.triage"].sudo()
            create_vals = []
            for user in internal_users:
                vals = (
                    self.env["project.task"]
                    .with_context(lang=user.lang)
                    ._prepare_default_triage_vals(user.id)
                )
                create_vals.extend(vals)

            dbg.lifecycle.debug(
                "res.users._onboard_users_into_project: %s -> %d triage buckets",
                dbg.rec(internal_users),
                len(create_vals),
            )
            if create_vals:
                TriageSudo.with_context(default_project_id=False).create(create_vals)

            return internal_users
        dbg.logic.debug(
            "res.users._onboard_users_into_project: %s are all share users, skipped",
            dbg.rec(users),
        )
        return None

    @dbg.timed
    def _get_calendars_validity_within_period(self, start, end):
        assert start.tzinfo and end.tzinfo
        user_resources = {user: user._get_project_task_resource() for user in self}
        user_calendars_within_period = defaultdict(lambda: defaultdict(Intervals))
        resource_calendars_within_period = (
            self._get_project_task_resource()._get_calendars_validity_within_period(
                start, end
            )
        )
        if not self:
            user_calendars_within_period[False] = resource_calendars_within_period[
                False
            ]
        for user, resource in user_resources.items():
            if resource:
                user_calendars_within_period[user.id] = (
                    resource_calendars_within_period[resource.id]
                )
            else:
                calendar = (
                    user.resource_calendar_id
                    or user.company_id.resource_calendar_id
                    or self.env.company.resource_calendar_id
                )
                user_calendars_within_period[user.id][calendar] = Intervals(
                    [(start, end, self.env["resource.calendar.attendance"])]
                )
        return user_calendars_within_period

    @dbg.timed
    def _get_valid_work_intervals(self, start, end, calendars=None):
        assert start.tzinfo and end.tzinfo
        user_calendar_validity_intervals = {}
        calendar_users = defaultdict(lambda: self.env["res.users"])
        user_work_intervals = defaultdict(Intervals)
        calendar_work_intervals = {}
        user_resources = {user: user._get_project_task_resource() for user in self}

        user_calendar_validity_intervals = self._get_calendars_validity_within_period(
            start, end
        )
        for user in self:
            for calendar in user_calendar_validity_intervals[user.id]:
                calendar_users[calendar] |= user
        for calendar in calendars or []:
            calendar_users[calendar] |= self.env["res.users"]
        dbg.logic.debug(
            "res.users._get_valid_work_intervals %s %s..%s: %d calendars",
            dbg.rec(self),
            start,
            end,
            len(calendar_users),
        )
        for calendar, users in calendar_users.items():
            if not calendar:
                continue
            with dbg.timer(
                self.env,
                "_get_valid_work_intervals: calendar %s for %d users",
                calendar.id,
                len(users),
            ):
                work_intervals_batch = calendar._work_intervals_batch(
                    start, end, resources=users._get_project_task_resource()
                )
            for user in users:
                user_work_intervals[user.id] |= (
                    work_intervals_batch[user_resources[user].id]
                    & user_calendar_validity_intervals[user.id][calendar]
                )
            calendar_work_intervals[calendar.id] = work_intervals_batch[False]

        return user_work_intervals, calendar_work_intervals

    def _get_project_task_resource(self):
        return self.env["resource.resource"]
