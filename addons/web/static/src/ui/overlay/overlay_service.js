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
        // Ids whose removal is in flight. A closer may be invoked more than once
        // before its async ``onRemove`` settles (e.g. action_service calls the
        // dialog's ``remove()`` while a re-entrant ``onRemove`` also fires, or
        // OverlayContainer.handleError removes a crashing overlay). Tracking the
        // in-flight ids makes ``remove`` idempotent internally so ``onRemove``
        // runs exactly once and consumers don't each need their own guard.
        const removing = new Set();

        // No props: OverlayContainer reads the overlays from ITS env's overlay
        // service. Passing `overlays` through the registry entry would bind
        // every rendered container (one per WebClient) to the overlays of the
        // service instance that registered last — with several mock envs in
        // tests, overlays opened from the other envs would render nowhere.
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
         * @returns {() => void}
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
