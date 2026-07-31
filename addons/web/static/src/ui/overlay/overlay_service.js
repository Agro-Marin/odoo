// @ts-check
/** @odoo-module native */

/** @module @web/ui/overlay/overlay_service */

import { markRaw, reactive } from "@odoo/owl";
import { mainComponentEntry } from "@web/components/main_components_container";
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

export const overlayService = {
    start() {
        let nextId = 0;
        const overlays = reactive(/** @type {Record<number, any>} */ ({}));
        const removing = new Set();

        mainComponents.add("OverlayContainer", mainComponentEntry(OverlayContainer));

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
         * @returns {(removeParams?: any) => Promise<void>}
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

        return {
            add,
            overlays,
            destroy() {
                for (const id of Object.keys(overlays)) {
                    overlays[Number(id)].remove().catch(() => {});
                }
            },
        };
    },
};

services.add("overlay", overlayService);
