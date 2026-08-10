// @ts-check
/** @odoo-module native */

/** @module @web/fields/field_handle */

import { useComponent } from "@odoo/owl";

/**
 * The field a widget is rendering: its value, its definition, and how to write
 * it back.
 *
 * Most field widgets need exactly this much of the record. Measured across the
 * fork by `tooling/architecture/js_field_record_surface.py`: of 155 widgets, 101
 * never name a field other than their own, and inside `addons/web/fields/` 44 of
 * 59 reach nothing beyond `data`, `update`, `fields`, `resId` and `resModel`.
 * They express it the long way round —
 *
 * ```js
 * this.props.record.data[this.props.name]
 * this.props.record.fields[this.props.name]
 * this.props.record.update({ [this.props.name]: value })
 * ```
 *
 * — three spellings of "my value", "my definition", "set my value", each
 * re-deriving the pairing of record and name at every call site.
 *
 * ## Why this is a hook and not a prop
 *
 * The obvious design is a `field` prop built by `Field` and handed down. It
 * cannot work, and the reason is the one recorded in
 * `machine_doc_v1/STATE_MANAGEMENT.md`: OWL keys a subscription on the **proxy a
 * read travels through**, at the moment of the read. A handle built in the
 * parent closes over the *parent's* proxy, so every read through it subscribes
 * the parent — the child renders once with the right value and then never
 * updates.
 *
 * That is not a deduction, it is measured: `field_handle.test.js` mounts both
 * shapes. A parent-built handle fails to re-render the child even when the
 * parent wraps the record in `useState` first; a handle built inside the
 * consuming component passes.
 *
 * So the handle is constructed by the widget, in its own `setup()`, and every
 * accessor reads **lazily through `component.props`**. Reading lazily rather
 * than capturing `props.record` once is what makes it survive a swapped record
 * prop — an x2many row reusing a component instance for a different record —
 * which the same suite pins.
 *
 * ## What this does not change
 *
 * `standardFieldProps` is untouched and `props.record` stays exactly where it
 * was. That is deliberate: 155 widgets live across four checkouts that cannot be
 * committed atomically, so a replacement would break every downstream addon at
 * the moment web landed. This is additive. A widget adopts it one at a time, the
 * 38 widgets that genuinely need the record keep using it, and
 * `js_field_record_surface` measures the balance either way.
 *
 * @returns {FieldHandle}
 */
export function useFieldHandle() {
    const component = /** @type {any} */ (useComponent());
    return {
        get name() {
            return component.props.name;
        },
        get value() {
            return component.props.record.data[component.props.name];
        },
        get field() {
            return component.props.record.fields[component.props.name];
        },
        get type() {
            return component.props.record.fields[component.props.name].type;
        },
        get readonly() {
            return Boolean(component.props.readonly);
        },
        update(value, options) {
            return component.props.record.update(
                { [component.props.name]: value },
                options,
            );
        },
    };
}

/**
 * @typedef {{
 *  readonly name: string,
 *  readonly value: any,
 *  readonly field: Record<string, any>,
 *  readonly type: string,
 *  readonly readonly: boolean,
 *  update: (value: any, options?: { save?: boolean }) => Promise<void>,
 * }} FieldHandle
 */
