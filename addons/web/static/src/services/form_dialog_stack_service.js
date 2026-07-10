// @ts-check
/** @odoo-module native */

/** @module @web/services/form_dialog_stack_service - Shared count of currently-open form-in-dialog instances */

import { registry } from "@web/core/registry";

/**
 * Single source of truth for how many form-in-dialog instances are open
 * across the page. Replaces a per-FormController counter that had a latent
 * bug: a controller mounted after a dialog opened would see count === 0,
 * since the counter was scoped to the controller's lifetime, not the page.
 *
 * An earlier revision exposed the count via bus events
 * (``AppEvent.FORM_DIALOG_ADD``/``REMOVE``) kept "for hypothetical external
 * listeners" that never materialized; replaced with direct ``push()``/
 * ``pop()`` calls from ``useFormViewInDialog``.
 *
 * @typedef {{
 *   push: () => void,
 *   pop: () => void,
 *   readonly count: number,
 *   readonly isEmpty: boolean,
 * }} FormDialogStackService
 */
export const formDialogStackService = {
    /**
     * @returns {FormDialogStackService}
     */
    start() {
        let count = 0;
        return {
            /** Increment the open-form-in-dialog counter. */
            push() {
                count++;
            },
            /** Decrement the open-form-in-dialog counter (floored at 0). */
            pop() {
                if (count === 0) {
                    // Unbalanced pop(): without a floor this drives count
                    // negative, leaving isEmpty falsy forever. Clamp, and
                    // surface the mismatch in dev mode.
                    if (odoo.debug) {
                        console.warn(
                            "[form_dialog_stack] pop() called with no open form-in-dialog (unbalanced push/pop)",
                        );
                    }
                    return;
                }
                count--;
            },
            /** Number of form-in-dialog instances currently open. */
            get count() {
                return count;
            },
            /** Convenience boolean: ``count === 0``. */
            get isEmpty() {
                return count === 0;
            },
        };
    },
};

registry.category("services").add("form_dialog_stack", formDialogStackService);
