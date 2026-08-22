// @ts-check
/** @odoo-module native */

import { onWillDestroy, useComponent } from "@odoo/owl";
import { ModelEvent } from "@web/core/events";

/**
 * @typedef {{ id: symbol, isDirty: boolean }} FieldDirtyPayload
 */

/**
 * @param {Set<symbol>} owners
 * @param {boolean | FieldDirtyPayload} detail
 * @returns {Set<symbol>}
 */
export function applyFieldDirtyPayload(owners, detail) {
    if (detail === null || typeof detail !== "object") {
        const message =
            "FIELD_IS_DIRTY was triggered with a raw boolean detail; emit an " +
            "owned payload through useFieldDirtySignal() instead. The legacy " +
            "boolean form shared one owner across all such emitters and " +
            "corrupted the aggregate dirty state, so it is no longer applied.";
        if (/** @type {any} */ (globalThis).odoo?.debug) {
            throw new Error(message);
        }
        console.warn(message);
        return owners;
    }
    const { id, isDirty } = /** @type {FieldDirtyPayload} */ (detail);
    if (isDirty) {
        owners.add(id);
    } else {
        owners.delete(id);
    }
    return owners;
}

/**
 * @param {{ bus: import("@odoo/owl").EventBus }} [model]
 * @returns {(isDirty: boolean) => void}
 */
export function useFieldDirtySignal(model) {
    const component = useComponent();
    const getBus = () =>
        (model ?? /** @type {any} */ (component).props.record.model).bus;
    const id = Symbol("field-dirty-owner");
    let lastReported = false;

    const setDirty = (/** @type {boolean} */ isDirty) => {
        isDirty = Boolean(isDirty);
        if (isDirty === lastReported) {
            return;
        }
        lastReported = isDirty;
        getBus().trigger(ModelEvent.FIELD_IS_DIRTY, { id, isDirty });
    };

    onWillDestroy(() => setDirty(false));
    return setDirty;
}
