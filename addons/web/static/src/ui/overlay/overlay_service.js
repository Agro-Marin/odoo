// @ts-check
/** @odoo-module native */

/** @module @web/ui/overlay/overlay_service - Low-level service for adding/removing overlay components (popovers, dialogs, effects) */

import { markRaw, reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { OverlayContainer } from "@web/ui/overlay/overlay_container";

const mainComponents = registry.category("main_components");
const services = registry.category("services");

/**
 * @typedef {{
 *  env?: object;
 *  onRemove?: (params?: any) => void;
 *  sequence?: number;
 *  rootId?: string;
 * }} OverlayServiceAddOptions
 */

/**
 * Low-level service for adding/removing overlay components (popovers, dialogs, effects).
 *
 * Manages a reactive registry of overlay entries rendered by `OverlayContainer`.
 * Higher-level services (popover, dialog, bottom_sheet, effect) build on top of this.
 */
export const overlayService = {
    start() {
        let nextId = 0;
        const overlays = reactive(/** @type {Record<number, any>} */ ({}));
        const removing = new Set();

        mainComponents.add("OverlayContainer", {
            Component: /** @type {any} */ (OverlayContainer),
        });

        const remove = async (
            /** @type {number} */ id,
            onRemove = /** @type {(params?: any) => void} */ (() => {}),
            /** @type {any} */ removeParams,
        ) => {
            if (!(id in overlays) || removing.has(id)) {
                return;
            }
            removing.add(id);
            try {
                await onRemove(removeParams);
            } finally {
                removing.delete(id);
                delete overlays[id];
            }
        };

        /**
         * @param {import("@odoo/owl").ComponentConstructor} component
         * @param {object} props
         * @param {OverlayServiceAddOptions} [options]
         * @returns {(removeParams?: any) => Promise<void>} resolves once
         *  `options.onRemove` has settled and the overlay is gone. Calling it
         *  more than once is a no-op: the first call owns the removal.
         */
        const add = (component, props, options = {}) => {
            const id = ++nextId;
            const removeCurrentOverlay = (
                /** @type {any} */ removeParams = undefined,
            ) => remove(id, options.onRemove, removeParams);
            overlays[id] = {
                id,
                component,
                env: options.env && markRaw(options.env),
                props,
                remove: removeCurrentOverlay,
                sequence: options.sequence ?? 50,
                rootId: options.rootId,
            };
            return removeCurrentOverlay;
        };

        return { add, overlays };
    },
};

services.add("overlay", overlayService);
