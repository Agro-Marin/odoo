// @ts-check
/** @odoo-module native */
import { useDialogContext } from "@web/core/dialog_context_hooks";
import { Model, useViewModel } from "@web/model/model";

/**
 * @typedef {import("@web/model/model").ViewContext & {
 * model: any;
 * inDialog: boolean | undefined;
 * }} ViewScope
 */

/** @returns {ViewScope} */
export function useViewScope() {
    const scope = /** @type {ViewScope} */ (Model.useViewContext());
    scope.model = useViewModel();
    scope.inDialog = useDialogContext().inDialog;
    return scope;
}
