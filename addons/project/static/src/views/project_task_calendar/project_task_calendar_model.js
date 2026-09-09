/** @odoo-module native */
import { Domain } from "@web/core/domain";
import { deserializeDate, serializeDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/translation";
import { CalendarModel } from "@web/views/calendar";

import { useProjectModelActions } from "../project_highlight_tasks.js";
import { ProjectTaskModelMixin } from "../project_task_model_mixin.js";

export class ProjectTaskCalendarModel extends ProjectTaskModelMixin(CalendarModel) {
    setup() {
        super.setup(...arguments);
        this.getHighlightIds = useProjectModelActions({
            getContext: () => this.env.searchModel.context,
        }).getHighlightIds;
    }

    get tasksToPlanDomain() {
        const projectId = this.meta.context.default_project_id;
        const domain = [
            ["date_end", "=", false],
            ["date_start", "=", false],
        ];
        if (projectId) {
            domain.push(["project_id", "=", projectId]);
        }
        return domain;
    }

    makeContextDefaults(record) {
        const { default_date_start_effective, ...context } = super.makeContextDefaults(
            record,
        );
        if (this.planStartsAtCalendarClick(default_date_start_effective, context)) {
            context.default_date_start = default_date_start_effective;
        }

        return { ...context, scale: this.meta.scale };
    }

    /**
     * @param {string} start
     * @param {Object} context
     * @returns {boolean}
     */
    planStartsAtCalendarClick(start, context) {
        return (
            ["day", "week"].includes(this.meta.scale) ||
            !deserializeDate(start).hasSame(
                deserializeDate(context["default_date_end"]),
                "day",
            )
        );
    }

    /** @override */
    get defaultFilterLabel() {
        this.isCheckProject = "project_id" in this.meta.filtersInfo;
        if (this.isCheckProject) {
            return _t("Private");
        }
        return super.defaultFilterLabel;
    }

    get tasksToPlanSpecification() {
        return {
            name: {},
        };
    }

    async load(params = {}) {
        return super.load({
            planTask: false,
            ...params,
        });
    }

    get tasksToPlan() {
        return this.data?.tasksToPlan;
    }

    async loadRecords(data) {
        this.highlightIds = await this.getHighlightIds();
        const keepCurrentList = !this.meta.showTasksToPlan || this.meta.planTask;
        const [records, tasksToPlan] = await Promise.all([
            super.loadRecords(data),
            keepCurrentList ? this.data?.tasksToPlan : this._fetchTasksToPlan({ data }),
        ]);
        data.tasksToPlan = tasksToPlan;
        return records;
    }

    async loadMoreTasksToPlan() {
        const { records, length } = this.tasksToPlan;
        const offset = records.length;
        const limit = Math.min(20, length - offset);
        if (limit <= 0) {
            return;
        }
        const { records: newRecords } = await this._fetchTasksToPlan({ limit, offset });
        this.tasksToPlan.records.push(...newRecords);
        this.notify();
    }

    async _fetchTasksToPlan({ data, limit, offset }) {
        const projectId = this.meta.context.default_project_id;
        if (!projectId) {
            return { records: [], length: 0 };
        }
        const { date_start, date_stop } = this.meta.fieldMapping;
        const fieldsToRemove = [
            ...new Set([date_start, date_stop, "date_start", "date_end"]),
        ];
        let domain = Domain.removeDomainLeaves(
            Domain.and([
                this.meta.domain,
                this.computeFiltersDomain(data || this.data),
            ]),
            fieldsToRemove,
        );
        domain = Domain.and([domain, this.tasksToPlanDomain]);
        return await this.orm.webSearchRead(
            this.resModel,
            domain.toList(this.meta.context),
            {
                specification: this.tasksToPlanSpecification,
                limit: limit || 20,
                offset: offset || 0,
            },
        );
    }

    _getPlanTaskVals(taskToPlan, date, timeSlotSelected = false) {
        const [, end] = this.getAllDayDates(date, date);
        const vals = { date_end: serializeDateTime(end) };
        if (timeSlotSelected) {
            vals.date_start = serializeDateTime(date);
            vals.date_end = serializeDateTime(date.plus({ hours: 1 }));
        } else if (["day", "week"].includes(this.meta.scale)) {
            const [start, allDayEnd] = this.getAllDayDates(date, date);
            vals.date_start = serializeDateTime(start);
            vals.date_end = serializeDateTime(allDayEnd);
        }
        return vals;
    }

    _getPlanTaskContext(taskToPlan, timeSlotSelected) {
        return {
            ...this.meta.context,
            task_calendar_plan_full_day:
                ["day", "week"].includes(this.meta.scale) && !timeSlotSelected,
        };
    }

    async planTask(taskId, date, timeSlotSelected = false) {
        const taskToPlan = this.tasksToPlan.records.find((task) => task.id === taskId);
        if (!taskToPlan) {
            return;
        }
        const context = this._getPlanTaskContext(taskToPlan, timeSlotSelected);
        await this.orm.call(
            this.meta.resModel,
            "plan_task_in_calendar",
            [[taskId], this._getPlanTaskVals(taskToPlan, date, timeSlotSelected)],
            {
                context,
            },
        );
        const taskToPlanIndex = this.tasksToPlan.records.indexOf(taskToPlan);
        if (taskToPlanIndex >= 0) {
            this.tasksToPlan.records.splice(taskToPlanIndex, 1);
            this.tasksToPlan.length -= 1;
        }
        await this.load({ planTask: true });
    }
}
