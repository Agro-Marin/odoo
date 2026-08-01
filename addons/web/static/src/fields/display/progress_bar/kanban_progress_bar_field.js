// @ts-check
/** @odoo-module native */

/** @module @web/fields/display/progress_bar/kanban_progress_bar_field */

import { registerField } from "@web/fields/_registry";

import { ProgressBarField, progressBarField } from "./progress_bar_field.js";

/**
 * A kanban card is never "in edition", so the base `isEditable` -- which ands in
 * `!props.readonly` -- used to be false for every card. This class existed to
 * override that by dropping the `readonly` term altogether, which also threw
 * away the field's own `readonly` modifier: `readonly="1"` on an editable
 * progressbar had no effect in kanban.
 *
 * `interactiveOutsideEdition` says the same thing without the collateral --
 * `props.readonly` becomes the modifier alone -- so the base class is correct
 * here and the subclass is gone. The alias is kept for the widgets extending it.
 */
export const KanbanProgressBarField = ProgressBarField;

export const kanbanProgressBarField = {
    ...progressBarField,
    component: KanbanProgressBarField,
    interactiveOutsideEdition: true,
};

registerField({ name: "progressbar", view: "kanban" }, kanbanProgressBarField);
