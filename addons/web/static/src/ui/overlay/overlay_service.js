// @ts-check
/** @odoo-module native */

/** @module @web/ui/overlay/overlay_service */

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
 *  env?: object;
 *  onRemove?: (params?: any) => void;
 *  sequence?: number;
 *  rootId?: string;
 * }} OverlayServiceAddOptions
 */

/**
 * The `overlay` service.
 *
 * A class rather than a closure returning an object literal; see
 * `core/hotkeys/hotkey_service.js` for the reasoning and
 * `tooling/architecture/js_service_shape.py` for the budget.
 *
 * `_remove` is underscored because the closure published `{ add, overlays,
 * destroy }` and kept removal inside: callers get a remover from `add()`, and
 * each overlay carries its own on `overlays[id].remove`. A class exposes every
 * prototype method, so leaving the name bare would have added a public
 * entry point the service never had.
 */
export class OverlayService {
    constructor() {
        this.nextId = 0;
        this.overlays = reactive(/** @type {Record<number, any>} */ ({}));
        /** @type {Map<number, Promise<void>>} the removal in flight per overlay */
        this.removing = new Map();

        mainComponents.add("OverlayContainer", mainComponentEntry(OverlayContainer));
    }

    /**
     * Resolves when the overlay is actually gone, which is after the
     * caller's `onRemove` has settled. A second call joins the first rather
     * than reporting success straight away: closing twice is ordinary --
     * `usePopover` closes on unmount and again when reopened -- and the
     * second caller is owed the same answer as the first, not one that
     * arrives while the overlay is still on screen.
     *
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
            return pending;
        }
        // Registered BEFORE `onRemove` runs: its synchronous part executes
        // immediately, so a caller that closes again from inside it has to
        // find this removal already in flight or it would start a second.
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
            props,
            remove: removeCurrentOverlay,
            sequence: options.sequence ?? DEFAULT_OVERLAY_SEQUENCE,
            rootId: options.rootId,
        };
        return removeCurrentOverlay;
    }

    destroy() {
        for (const id of Object.keys(this.overlays)) {
            // Swallowed HERE and nowhere else, deliberately. On the
            // normal path a rejecting `onClose` belongs to the caller
            // that asked to close, and reaches the global handler if it
            // is not caught. Teardown has no such caller: the entry is
            // already dropped in `_remove`'s `finally`, so the rejection
            // could only surface later and fail whatever unrelated work
            // ran next. Routing it through `reportUncaught` does not
            // help -- that is a microtask `throw`, i.e. the same
            // unhandled rejection by another name.
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
