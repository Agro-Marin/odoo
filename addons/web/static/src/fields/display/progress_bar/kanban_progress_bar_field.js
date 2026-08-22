// @ts-check
/** @odoo-module native */

import { registerField } from "@web/fields/_registry";

import { ProgressBarField, progressBarField } from "./progress_bar_field.js";

export const KanbanProgressBarField = ProgressBarField;

export const kanbanProgressBarField = {
    ...progressBarField,
    component: KanbanProgressBarField,
    interactiveOutsideEdition: true,
};

registerField({ name: "progressbar", view: "kanban" }, kanbanProgressBarField);
