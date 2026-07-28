// @ts-check
/** @odoo-module native */

/** @module @web/fields/field_dirty_signal - Owner-keyed "this field has uncommitted input" signal */

import { onWillDestroy, useComponent } from "@odoo/owl";
import { ModelEvent } from "@web/core/events";

/**
 * ``FIELD_IS_DIRTY`` announces "a field holds input it has not committed to the
 * record yet" — the window between a keystroke and the blur/Tab that writes it.
 *
 * It used to carry a bare boolean on a shared bus, which made it
 * last-writer-wins across every field of the record: whichever field spoke most
 * recently spoke for all of them. Two consequences, both reproduced:
 *
 *  - a field going dirty→clean cleared the signal while a DIFFERENT field still
 *    held uncommitted text, so the form advertised itself as saved;
 *  - a field emitting ``false`` on its first render (a clean field has a
 *    transition to report the moment it mounts) cancelled a dirty sibling.
 *
 * Both were patched per-widget, by hand, with a ``lastIsDirty`` field guarding
 * the transition — in DateTimeField and in DomainField, with the same six-line
 * comment in each, and absent from every other emitter. That guard cannot fix
 * the first case anyway: a field that genuinely goes clean DID transition, and
 * still speaks for its siblings.
 *
 * So the payload is keyed by owner instead. Each emitter reports only its own
 * state, the consumer keeps the set of currently-dirty owners, and the answer
 * is "is that set non-empty" — order-independent, and correct with any number
 * of fields.
 *
 * @typedef {{ id: symbol, isDirty: boolean }} FieldDirtyPayload
 */

/**
 * Legacy key for emitters that still publish a bare boolean
 * (``bus.trigger("FIELD_IS_DIRTY", true)``): html_editor, mass_mailing and the
 * enterprise ai prompt field. They keep their old last-writer-wins semantics
 * among themselves, under one shared key, and compose correctly with keyed
 * emitters — a keyed field going clean can no longer clear their flag, which is
 * the bug this module exists to remove.
 */
const LEGACY_OWNER = Symbol("legacy-field-dirty-emitter");

/**
 * Fold one ``FIELD_IS_DIRTY`` payload into the set of dirty owners.
 * Accepts both the keyed and the bare-boolean shapes.
 *
 * @param {Set<symbol>} owners mutated in place
 * @param {boolean | FieldDirtyPayload} detail
 * @returns {Set<symbol>} the same set, for call-site convenience
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
 * Publish this component's own "holds uncommitted input" state.
 *
 * Returns a setter that is idempotent (re-reporting an unchanged state emits
 * nothing) and self-clearing: a component destroyed while dirty retracts its
 * claim, so a field unmounted mid-edit — a list row leaving edit mode, an
 * x2many line removed — cannot leave the record permanently marked dirty.
 *
 * @param {{ bus: import("@web/core/utils/hooks").EventBus }} [model] defaults to
 *  the component's own ``props.record.model``
 * @returns {(isDirty: boolean) => void}
 */
export function useFieldDirtySignal(model) {
    const component = useComponent();
    // Resolved per emit, not captured at setup: every previous emitter read
    // ``props.record.model.bus`` at trigger time, and a field component can be
    // handed a record from a different datapoint tree across its lifetime.
    const getBus = () =>
        (model ?? /** @type {any} */ (component).props.record.model).bus;
    const id = Symbol("field-dirty-owner");
    let lastReported = false;

    const setDirty = (isDirty) => {
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
