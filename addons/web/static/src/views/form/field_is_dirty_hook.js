// @ts-check
/** @odoo-module native */

import { useState } from "@odoo/owl";
import { ModelEvent } from "@web/core/events";
import { useBus } from "@web/core/utils/hooks";
import { applyFieldDirtyPayload } from "@web/fields/field_dirty_signal";

/**
 * @param {Record<string, any>} model
 * @returns {() => boolean}
 */
export function useFieldIsDirty(model) {
    const dirtyOwners = new Set();
    const state = useState({ fieldIsDirty: false });
    useBus(model.bus, ModelEvent.FIELD_IS_DIRTY, (ev) => {
        state.fieldIsDirty = applyFieldDirtyPayload(dirtyOwners, ev.detail).size > 0;
    });
    return () => model.root.dirty || state.fieldIsDirty;
}
