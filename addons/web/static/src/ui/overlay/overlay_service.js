// @ts-check
/** @odoo-module native */

import { markRaw, reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { mainComponentEntry } from "@web/ui/main_components_container";
import {
    DEFAULT_OVERLAY_SEQUENCE,
    OverlayContainer,
} from "@web/ui/overlay/overlay_container";

const mainComponents = registry.category("main_components");
const services = registry.category("services");

/**
 * @typedef {{
 * env?: object;
 * onRemove?: (params?: any) => void;
 * sequence?: number;
 * rootId?: string;
 * }} OverlayServiceAddOptions
 */

class OverlayService {
    constructor() {
        this.nextId = 0;
        this.overlays = reactive(/** @type {Record<number, any>} */ ({}));
        /** @type {Map<number, Promise<void>>} */
        this.removing = new Map();

        mainComponents.add("OverlayContainer", mainComponentEntry(OverlayContainer));
    }

    /**
     * @param {number} id
     * @param {(params?: any) => any} [onRemove]
     * @param {any} [removeParams]
     * @returns {Promise<void>}
     */
    _remove(id, onRemove = () => {}, removeParams) {
        if (!(id in this.overlays)) {
            return Promise.resolve();
        }
        const pending = this.removing.get(id);
        if (pending) {
            if (odoo.debug && removeParams !== undefined) {
                console.warn(
                    `[overlay] closing overlay ${id} again while its removal ` +
                        `is in flight: the provided removeParams are ignored.`,
                );
            }
            return pending;
        }
        const { promise, resolve, reject } = /** @type {PromiseWithResolvers<void>} */ (
            Promise.withResolvers()
        );
        this.removing.set(id, promise);
        (async () => {
            try {
                await onRemove(removeParams);
                resolve();
            } catch (error) {
                reject(error);
            } finally {
                this.removing.delete(id);
                delete this.overlays[id];
            }
        })();
        return promise;
    }

    /**
     * @param {import("@odoo/owl").ComponentConstructor} component
     * @param {object} props
     * @param {OverlayServiceAddOptions} [options]
     * @returns {(removeParams?: any) => Promise<void>}
     */
    add(component, props, options = {}) {
        const id = ++this.nextId;
        const removeCurrentOverlay = (/** @type {any} */ removeParams = undefined) =>
            this._remove(id, options.onRemove, removeParams);
        this.overlays[id] = {
            id,
            component,
            env: options.env && markRaw(options.env),
            props: props && markRaw(props),
            remove: removeCurrentOverlay,
            sequence: options.sequence ?? DEFAULT_OVERLAY_SEQUENCE,
            rootId: options.rootId,
        };
        return removeCurrentOverlay;
    }

    destroy() {
        for (const id of Object.keys(this.overlays)) {
            this.overlays[Number(id)].remove().catch(() => {});
        }
    }
}

export const overlayService = {
    /**
     * @returns {OverlayService}
     */
    start() {
        return new OverlayService();
    },
};

services.add("overlay", overlayService);
