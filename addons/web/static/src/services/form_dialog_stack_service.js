// @ts-check
/** @odoo-module native */

/** @module @web/services/form_dialog_stack_service - Shared count of currently-open form-in-dialog instances */

import { registry } from "@web/core/registry";

/**
 * Single source of truth for "how many form-in-dialog instances are
 * currently open across the page".  Replaces the per-FormController
 * counter that incremented/decremented on every form-in-dialog
 * mount/unmount.
 *
 * The counter pattern was wasteful (every FormController on the page
 * maintained its own counter from the same global events) and had a
 * latent bug: a controller mounted *after* a form-in-dialog opened
 * would see ``count === 0`` even though a dialog was already open,
 * because the counter was scoped to the controller's lifetime rather
 * than to the page.  The shared service fixes both.
 *
 * Historical note: an earlier revision exposed the count by
 * subscribing to ``AppEvent.FORM_DIALOG_ADD`` /
 * ``AppEvent.FORM_DIALOG_REMOVE`` bus events that
 * ``useFormViewInDialog`` triggered on mount/unmount.  The events
 * were preserved "for hypothetical external listeners".  None
 * materialized — the trigger and the listener were both inside the
 * web module, with no consumer of the events outside the
 * service-listener pairing they implemented.  The bus indirection
 * was removed in favor of direct ``push()`` / ``pop()`` calls from
 * ``useFormViewInDialog`` (one fewer hop, one fewer pair of
 * constants in events.js, no scaffolding waiting for consumers that
 * never came).
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
