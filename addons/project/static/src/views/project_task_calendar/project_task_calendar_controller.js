/** @odoo-module native */
import { useRef } from "@odoo/owl";

import { _t } from "@web/core/l10n/translation";
import { DateTime } from "@web/core/l10n/luxon";
import { CalendarController } from "@web/views/calendar/calendar_controller";
import { subTaskDeleteConfirmationMessage } from "@project/views/project_task_form/project_task_form_controller";

import { ProjectTaskCalendarSidePanel } from "./side_panel/project_task_calendar_side_panel.js";
import { useCalendarTaskToPlanDraggable } from "./hooks/project_task_calendar_task_to_plan_draggable.js";

export class ProjectTaskCalendarController extends CalendarController {
    static components = {
        ...ProjectTaskCalendarController.components,
        CalendarSidePanel: ProjectTaskCalendarSidePanel,
    };

    setup() {
        super.setup();
        this.rootRef = useRef("root");
        if (this.canDragAndDropRecord) {
            useCalendarTaskToPlanDraggable({
                ref: this.rootRef,
                elements: ".o_task_to_plan_draggable",
                ignore: "button",
                onElementEnter: ({ addClass, element }) => {
                    addClass(element, "o-highlight");
                },
                onElementLeave: ({ removeClass, element }) => {
                    removeClass(element, "o-highlight");
                },
                onDrop: (params) => {
                    this.dropTaskToPlan(params);
                }
            });
        }
    }

    get modelParams() {
        return {
            ...super.modelParams,
            showTasksToPlan: this.canDragAndDropRecord,
        }
    }

    get editRecordDefaultDisplayText() {
        return _t("New Task");
    }

    get sidePanelProps() {
        return {
            ...super.sidePanelProps,
            editRecord: this.editRecord.bind(this),
        };
    }

    get canDragAndDropRecord() {
        return this.draggable && !this.env.isSmall;
    }

    get draggable() {
        return Boolean(this.props.context.default_project_id);
    }

    deleteConfirmationDialogProps(record) {
        const deleteConfirmationDialogProps = super.deleteConfirmationDialogProps(record);
        if  (!record.rawRecord.subtask_count) {
            return deleteConfirmationDialogProps;
        }

        return {
            ...deleteConfirmationDialogProps,
            body: subTaskDeleteConfirmationMessage,
        }
    }

    async dropTaskToPlan(params) {
        const { element, calendarCell, timeSlotElement } = params;
        const taskId = Number(element.dataset.resId);
        let dateStr = calendarCell.dataset.date;
        if (timeSlotElement) {
            dateStr += `T${timeSlotElement.dataset.time}`;
        }
        const date = DateTime.fromISO(dateStr);
        if (date.isValid) {
            element.hidden = true;
            try {
                await this.model.planTask(taskId, date, Boolean(timeSlotElement));
            } finally {
                // planTask reloads the list; only unhide if this node is still
                // in the DOM, and always unhide it even if planTask threw.
                if (element.isConnected) {
                    element.hidden = false;
                }
            }
        }
    }
}
