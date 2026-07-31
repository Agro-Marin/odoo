// @ts-check
/** @odoo-module native */

/** @module @web/fields/field_dirty_signal */

import { onWillDestroy, useComponent } from "@odoo/owl";
import { ModelEvent } from "@web/core/events";

/**
 * @typedef {{ id: symbol, isDirty: boolean }} FieldDirtyPayload
 */

const LEGACY_OWNER = Symbol("legacy-field-dirty-emitter");

/**
 * @param {Set<symbol>} owners
 * @param {boolean | FieldDirtyPayload} detail
 * @returns {Set<symbol>}
 */
export function applyFieldDirtyPayload(owners, detail) {
    const isPayload = detail !== null && typeof detail === "object";
    const id = isPayload ? /** @type {FieldDirtyPayload} */ (detail).id : LEGACY_OWNER;
    const isDirty = isPayload
        ? /** @type {FieldDirtyPayload} */ (detail).isDirty
        : Boolean(detail);
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
