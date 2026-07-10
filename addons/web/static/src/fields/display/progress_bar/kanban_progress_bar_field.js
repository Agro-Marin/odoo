// @ts-check
/** @odoo-module native */

/** @module @web/fields/display/progress_bar/kanban_progress_bar_field - Kanban-view variant of the progress bar field */

import { registerField } from "@web/fields/_registry";

import { ProgressBarField, progressBarField } from "./progress_bar_field.js";
export class KanbanProgressBarField extends ProgressBarField {
    /** @returns {boolean} Whether the bar is editable (ignores readonly, unlike parent). */
    get isEditable() {
        return this.props.isEditable;
    }
}

export const kanbanProgressBarField = {
    ...progressBarField,
    component: KanbanProgressBarField,
};

registerField({ name: "progressbar", view: "kanban" }, kanbanProgressBarField);
