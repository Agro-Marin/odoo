/** @odoo-module native */
import { Domain } from "@web/core/domain";
import { serializeDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { CalendarModel } from '@web/views/calendar/calendar_model';
import { ProjectTaskModelMixin } from "../project_task_model_mixin.js";

export class ProjectTaskCalendarModel extends ProjectTaskModelMixin(CalendarModel) {
    get tasksToPlanDomain() {
        const projectId = this.meta.context.default_project_id;
        const domain = [['date_end', '=', false]];
        if (projectId) {
            domain.push(['project_id', '=', projectId]);
        }
        return domain;
    }

    /**
     * @override
     */
    get defaultFilterLabel() {
        this.isCheckProject = 'project_id' in this.meta.filtersInfo;
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
        // Domain processing is handled by ProjectTaskModelMixin.load(); this
        // override only resets the planTask flag on regular loads.
        return super.load({
            planTask: false,
            ...params,
        });
    }

    /**
     * The to-plan list is staged on `data` and only becomes visible when the
     * base load() commits it (`this.data = data`), so a superseded or failed
     * load can never leave the side panel out of sync with the calendar
     * records (the base epoch/rollback protection covers it too).
     */
    get tasksToPlan() {
        return this.data?.tasksToPlan;
    }

    async loadRecords(data) {
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
        // `limit` is a page size, not an end index.
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
        const fieldsToRemove = [...new Set([date_start, date_stop, 'planned_date_begin', 'date_end'])]
        let domain = Domain.removeDomainLeaves(
            Domain.and([
                this.meta.domain,
                this.computeFiltersDomain(data || this.data),
            ]),
            fieldsToRemove
        );
        domain = Domain.and([
            domain,
            this.tasksToPlanDomain,
        ]);
        return await this.orm.webSearchRead(this.resModel, domain.toList(this.meta.context), {
            specification: this.tasksToPlanSpecification,
            limit: limit || 20,
            offset: offset || 0,
        });
    }

    _getPlanTaskVals(taskToPlan, date) {
        // NB: subclasses receive (taskToPlan, date, timeSlotSelected) via
        // ...arguments (cf. industry_fsm).
        const [, end] = this.getAllDayDates(date, date);
        return { date_end: serializeDateTime(end) };
    }

    _getPlanTaskContext(taskToPlan, timeSlotSelected) {
        return {
            ...this.meta.context,
            task_calendar_plan_full_day: ["day", "week"].includes(this.meta.scale) && !timeSlotSelected,
        };
    }

    async planTask(taskId, date, timeSlotSelected = false) {
        const taskToPlan = this.tasksToPlan.records.find((task) => task.id === taskId);
        if (!taskToPlan) {
            return;
        }
        const context = this._getPlanTaskContext(taskToPlan, timeSlotSelected);
        await this.orm.call(this.meta.resModel, "plan_task_in_calendar", [[taskId], this._getPlanTaskVals(taskToPlan, date, timeSlotSelected)], {
            context,
        });
        // Only drop the task from the side panel once the server accepted the
        // plan: if the RPC rejects, the task must stay droppable. Decrement
        // `length` in step with `records` (drives the "Load more" count).
        const taskToPlanIndex = this.tasksToPlan.records.indexOf(taskToPlan);
        if (taskToPlanIndex >= 0) {
            this.tasksToPlan.records.splice(taskToPlanIndex, 1);
            this.tasksToPlan.length -= 1;
        }
        await this.load({ planTask: true });
    }
}
