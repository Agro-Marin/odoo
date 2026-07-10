// @ts-check
/** @odoo-module native */

/** @module @web/ui/bottom_sheet/bottom_sheet_service - Service for programmatically showing mobile bottom sheet overlays */

import { markRaw } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { BottomSheet } from "@web/ui/bottom_sheet/bottom_sheet";

/**
 * @typedef {{
 *   env?: object;
 *   onClose?: () => void;
 *   class?: string;
 *   role?: string;
 *   ref?: Function;
 *   useBottomSheet?: Boolean;
 * }} BottomSheetServiceAddOptions
 *
 * @typedef {ReturnType<bottomSheetService["start"]>["add"]} BottomSheetServiceAddFunction
 */

/** Service for showing mobile-friendly bottom sheet overlays (slide-up panels). */
export const bottomSheetService = {
    dependencies: ["overlay"],
    /**
     * @param {import("@web/env").OdooEnv} _
     * @param {{ overlay: any }} services
     */
    start(_, { overlay }) {
        let bottomSheetCount = 0;
        /**
         * Signals the manager to add a popover.
         *
         * @param {HTMLElement} target
         * @param {import("@odoo/owl").ComponentConstructor} component
         * @param {object} [props]
         * @param {BottomSheetServiceAddOptions} [options]
         * @returns {() => void}
         */
        const add = (target, component, props = {}, options = {}) => {
            let closed = false;
            // Bookkeeping lives in onRemove (not the returned closer) so it fires on
            // every removal path, including OverlayContainer.handleError's direct
            // overlay.remove() when a subtree crashes — otherwise the count never
            // decrements and bottom-sheet-open sticks on <body> forever.
            const onRemove = async (/** @type {any} */ removeParams) => {
                // Close can be requested more than once (e.g. by concurrent
                // animation listeners): only decrement the count once.
                if (closed) {
                    return;
                }
                closed = true;
                await options.onClose?.(removeParams);
                bottomSheetCount--;
                if (bottomSheetCount === 0) {
                    document.body.classList.remove("bottom-sheet-open");
                } else if (bottomSheetCount === 1) {
                    document.body.classList.remove("bottom-sheet-open-multiple");
                }
            };
            const _remove = overlay.add(
                BottomSheet,
                {
                    close: () => _remove(),
                    component,
                    componentProps: markRaw(props),
                    ref: options.ref,
                    class: options.class,
                    role: options.role,
                },
                {
                    env: options.env,
                    onRemove,
                    rootId: /** @type {ShadowRoot} */ (target.getRootNode())?.host?.id,
                },
            );
            bottomSheetCount++;
            if (bottomSheetCount === 1) {
                document.body.classList.add("bottom-sheet-open");
            } else if (bottomSheetCount > 1) {
                document.body.classList.add("bottom-sheet-open-multiple");
            }

            return _remove;
        };

        return { add };
    },
};

registry.category("services").add("bottom_sheet", bottomSheetService);
