// @ts-check
/** @odoo-module native */

/** @module @web/views/form/field_is_dirty_hook - Shared "record has unsaved edits" signal for the form view */

import { useState } from "@odoo/owl";
import { ModelEvent } from "@web/core/events";
import { useBus } from "@web/core/utils/hooks";

/**
 * Subscribe to the form's "has unsaved edits" signal.
 *
 * ``record.dirty`` only rises once a field commits its change to the record
 * (on blur, Tab/Enter, or when a save asks for local changes). While the user
 * is still typing, the edit lives in the input element and the record is
 * indistinguishable from a pristine one. ``FIELD_IS_DIRTY`` covers exactly
 * that window, so callers must OR the two — reading either alone reports a
 * record with pending edits as saved.
 *
 * Both the status indicator and the form renderer's ``o_form_dirty`` /
 * ``o_form_saved`` classes derive from this single helper: when they each
 * carried their own notion, the indicator showed "unsaved" while the root
 * element still advertised ``o_form_saved``.
 *
 * @param {Object} model the relational model owning the bus
 * @returns {() => boolean} whether the record has committed or uncommitted edits
 */
export function useFieldIsDirty(model) {
    const state = useState({ fieldIsDirty: false });
    useBus(model.bus, ModelEvent.FIELD_IS_DIRTY, (ev) => {
        state.fieldIsDirty = ev.detail;
    });
    return () => model.root.dirty || state.fieldIsDirty;
}
