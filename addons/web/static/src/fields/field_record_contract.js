// @ts-check
/** @odoo-module native */

/** @module @web/fields/field_record_contract */

/**
 * What a field widget may reach on `props.record`.
 *
 * `standardFieldProps` is four keys and one of them is
 * `record: { type: Object }` — a live `RelationalRecord`, 83 own members before
 * anything inherited from `DataPoint` and `SignalStore`. Every field widget in
 * the fork receives all of it. Nothing said which parts were the contract, so
 * in practice the contract was "the record", and a change to any of those 83
 * members was a change to the interface of 155 widgets across four checkouts.
 *
 * This list is the statement. Measured, not guessed: `js_field_record_surface`
 * resolves the binding (only reads provably on `props.record`, never a loop
 * variable that happens to be called `record`, never a test fixture) and reports
 * what is actually reached.
 *
 * @type {string[]}
 */
export const FIELD_RECORD_SURFACE = [
    // the value the widget exists to render, and writing it back
    "data",
    "update",
    // field metadata
    "fields",
    "fieldNames",
    // identity of the record being edited
    "resId",
    "resModel",
    "id",
    "isNew",
    // evaluation context for domains and modifiers
    "context",
    "evalContext",
    "evalContextWithVirtualIds",
    // edit-state a widget consults before rendering or writing
    "dirty",
    "isInEdition",
    "isActive",
    "isValid",
    "isFieldInvalid",
    "setInvalidField",
    "resetFieldValidity",
    // record-level operations a widget can trigger
    "save",
    "discard",
    "load",
    // The whole model. Eleven widgets reach it — for `model.bus`, `model.load`,
    // `model.root`, `model.notify`, `model.config`, `model.multiEdit`. This is
    // the widest entry on the list by a distance: it hands a field widget the
    // loader, the mutex and every other record. It is declared because it is
    // reached, not because it is endorsed; `--json` names the eleven.
    "model",
];

/**
 * The narrow surface: everything a widget needs to render its OWN field value
 * and write it back.
 *
 * The measured split, which is the point of separating these two lists:
 *
 * | widgets | reach |
 * |---|---|
 * | 101 | this list only, and never a sibling field |
 * | 38 | name another field of the record by literal, or reach `record.model` |
 *
 * So a narrower `FieldHandle` prop — value, setter, type, modifiers — would
 * serve about two thirds of the widgets in the fork outright, and the remaining
 * third would keep `record` and be an explicitly declared exception rather than
 * an undifferentiated majority. That conversion is not this file; making it
 * derivable is.
 *
 * `record.data` reads split 175 own-field (`data[props.name]`) to 52 distinct
 * sibling names to 43 dynamic keys, so the majority of the traffic through the
 * widest member is a widget reading its own value the long way round. Those
 * figures are restated here as orientation only; they are measured by
 * `js_field_record_surface`, whose MEASURED block is the copy that cannot rot.
 *
 * @type {string[]}
 */
export const FIELD_OWN_VALUE_SURFACE = [
    "data",
    "update",
    "fields",
    "resId",
    "resModel",
    "isNew",
    "evalContext",
];

/**
 * The narrow surface as a type, for a widget that only renders its own field.
 *
 * @typedef {{
 *  data: Record<string, any>,
 *  update: (changes: Record<string, any>, options?: { save?: boolean }) => Promise<void>,
 *  fields: Record<string, any>,
 *  resId: number | false,
 *  resModel: string,
 *  isNew: boolean,
 *  evalContext: Record<string, any>,
 * }} FieldOwnValueContract
 */
