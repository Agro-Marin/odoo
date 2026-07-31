// @ts-check
/** @odoo-module native */

/** @module @web/fields/display/progress_bar/kanban_progress_bar_field */

import { registerField } from "@web/fields/_registry";

import { ProgressBarField, progressBarField } from "./progress_bar_field.js";
export class KanbanProgressBarField extends ProgressBarField {
    /** @returns {boolean} */
    get isEditable() {
        return Boolean(this.props.isEditable);
    }
}

export const kanbanProgressBarField = {
    ...progressBarField,
    component: KanbanProgressBarField,
};

registerField({ name: "progressbar", view: "kanban" }, kanbanProgressBarField);
