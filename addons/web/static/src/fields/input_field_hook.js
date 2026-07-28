// @ts-check
/** @odoo-module native */

/** @module @web/fields/input_field_hook - OWL hook that syncs an input element with the ORM record and handles dirty/parse/save lifecycle */

import { useComponent, useEffect, useRef } from "@odoo/owl";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { ModelEvent } from "@web/core/events";
import { useBus } from "@web/core/utils/hooks";
import { useFieldDirtySignal } from "@web/fields/field_dirty_signal";
import { ParseError } from "@web/fields/parse_error";

/**
 * For field components backed by an input/textarea: prevents the value from
 * being erased by a model update (e.g. an onchange) while the user is typing.
 *
 * @param {Object} params
 * @param {() => string} params.getValue a function that returns the value to write in
 *   the input, if the user isn't currently editing it
 * @param {(value: string) => any} [params.parse] a function that parses the value of the input.
 * @param {{ el: HTMLInputElement | HTMLTextAreaElement | null }} [params.ref] a ref containing the input/textarea
 * @param {string} [params.refName="input"] the ref name of the input/textarea
 * @param {boolean} [params.preventLineBreaks] Prevent line breaks in input when set
 * @param {string | null} [params.fieldName] the record field this input is bound
 *   to; defaults to the component's own ``props.name``. Pass an explicit falsy
 *   value to leave the hook UNBOUND — it then only returns the ref and touches
 *   neither the record nor the dirty signal.
 * @param {() => boolean} [params.shouldSave] if true, save the record with the new value
 * @returns {{ el: HTMLInputElement | HTMLTextAreaElement | null }} the input ref
 */
export function useInputField(params) {
    const inputRef = params.ref || useRef(params.refName || "input");
    const component = useComponent();
    const shouldSave = params.shouldSave ?? (() => false);

    // A caller that computes its field name may legitimately come up empty:
    // ProgressBarField binds a second input to its `max_value` field, and that
    // option is polymorphic — a literal bound (200) names no field at all. The
    // fallback to `props.name` then silently re-bound that input to the
    // PROGRESS field, i.e. to the same record field as the first input. It
    // never misbehaved only because the template also keeps the max input out
    // of the DOM in that case, so every code path happened to bail on a null
    // `inputRef.el` first — correct by coincidence, in two files that had to
    // agree. An unbound hook is now inert by construction.
    const fieldName = "fieldName" in params ? params.fieldName : component.props.name;
    if (!fieldName) {
        return inputRef;
    }
    // Reports only THIS input's state; the consumer aggregates across fields.
    // Emitting a bare boolean here meant an input returning to its original
    // value announced "nothing is dirty" on behalf of every other field on the
    // record.
    const setFieldDirty = useFieldDirtySignal();

    let isDirty = false;

    /**
     * The last value that has been commited to the model.
     * Not changed in case of invalid field value.
     */
    let lastSetValue = null;

    /**
     * Tracks a change sent to the model but not yet acknowledged (e.g. a pending
     * onchange), so it can be re-sent on an urgent save.
     * FIXME: this could/should be handled by the model itself, when it will be rewritten
     */
    let pendingUpdate = false;

    function onInput(ev) {
        isDirty = ev.target.value !== lastSetValue;
        if (params.preventLineBreaks && ev.inputType === "insertFromPaste") {
            ev.target.value = ev.target.value.replace(/[\r\n]+/g, " ");
        }
        setFieldDirty(isDirty);
        if (!component.props.record.isValid) {
            component.props.record.resetFieldValidity(fieldName);
        }
    }

    /**
     * Whether the parsed input value differs from the record's current value.
     *
     * Uses the ORM falsy-empty convention (``?? false``) so null/undefined and
     * ``false`` count as the same "empty" value. Shared by both commit paths
     * (blur and Tab/Enter/urgent) — they used to diverge (strict ``!==`` vs.
     * ``?? false``), causing a redundant ``record.update``/onchange RPC on one
     * path but not the other at the null-vs-false boundary.
     */
    function hasValueChanged(val) {
        return (val ?? false) !== (component.props.record.data[fieldName] ?? false);
    }

    /**
     * On blur, the field is no longer dirty even if invalid (an invalid value
     * is never committed). Delegates to ``commitChanges`` so blur and
     * Tab/Enter/urgent share one commit pipeline instead of drifting
     * hand-maintained copies (see ``hasValueChanged``); ``onInput`` maintains
     * ``isDirty ⇔ inputRef.el.value !== lastSetValue``, so recomputing it here
     * is equivalent to the old ``if (isDirty)`` guard.
     */
    function onChange() {
        return commitChanges(false);
    }
    function onKeydown(ev) {
        const hotkey = getActiveHotkey(ev);
        const keys = ["tab", "shift+tab"];
        if (ev.target.tagName.toLowerCase() !== "textarea") {
            keys.push("enter");
        }
        if (keys.includes(hotkey)) {
            commitChanges(false);
        }
        if (params.preventLineBreaks && ["enter", "shift+enter"].includes(hotkey)) {
            ev.preventDefault();
        }
    }

    useEffect(
        (inputEl) => {
            if (inputEl) {
                inputEl.addEventListener("input", onInput);
                inputEl.addEventListener("change", onChange);
                inputEl.addEventListener("keydown", onKeydown);
                return () => {
                    inputEl.removeEventListener("input", onInput);
                    inputEl.removeEventListener("change", onChange);
                    inputEl.removeEventListener("keydown", onKeydown);
                };
            }
        },
        () => [inputRef.el],
    );

    /**
     * A model patch may carry a new value for the field; skip it while the
     * user is typing (isDirty) or the field is invalid, otherwise apply it.
     */
    useEffect(() => {
        const value = params.getValue();
        if (
            inputRef.el &&
            !isDirty &&
            !component.props.record.isFieldInvalid(fieldName)
        ) {
            if (inputRef.el.value !== value) {
                const {
                    selectionStart,
                    selectionEnd,
                    value: previousValue,
                } = inputRef.el;
                const wasFullySelected =
                    selectionStart === 0 && selectionEnd === previousValue.length;
                inputRef.el.value = value;
                if (wasFullySelected && document.activeElement === inputRef.el) {
                    inputRef.el.select();
                }
            }
            lastSetValue = inputRef.el.value;
        }
    });

    const { model } = component.props.record;
    useBus(model.bus, ModelEvent.WILL_SAVE_URGENTLY, (ev) => {
        const prom = commitChanges(true);
        ev.detail?.proms?.push(prom);
    });
    useBus(model.bus, ModelEvent.NEED_LOCAL_CHANGES, (ev) =>
        ev.detail.proms.push(commitChanges()),
    );

    /**
     * Single commit pipeline, shared by blur (``onChange``), Tab/Enter
     * (``onKeydown``) and the urgent-save/local-changes bus events.
     *
     * @param {boolean} [urgent] re-commit even when not dirty if an update is
     *   still unacknowledged (``pendingUpdate``), so the value lands in the
     *   changes that the urgent save serialises; parse errors are silently
     *   dropped instead of flagging the field (the UI is going away).
     */
    async function commitChanges(urgent) {
        if (!inputRef.el) {
            return;
        }

        isDirty = inputRef.el.value !== lastSetValue;
        if (isDirty || (urgent && pendingUpdate)) {
            isDirty = false;
            let val = inputRef.el.value;
            if (params.parse) {
                try {
                    val = params.parse(val);
                } catch (error) {
                    if (!urgent) {
                        component.props.record.setInvalidField(fieldName);
                    }
                    if (!(error instanceof ParseError)) {
                        // Only a ParseError means "the user typed something we
                        // reject". Anything else is a defect in the parser; the
                        // field still goes invalid so the user isn't stuck, but
                        // the error is reported instead of vanishing here.
                        console.error(
                            `[useInputField] parsing "${fieldName}" threw a non-ParseError; ` +
                                `this is a widget defect, not invalid user input:`,
                            error,
                        );
                    }
                    return;
                }
            }

            if (hasValueChanged(val)) {
                lastSetValue = inputRef.el.value;
                pendingUpdate = true;
                try {
                    await component.props.record.update(
                        { [fieldName]: val },
                        { save: shouldSave() },
                    );
                } finally {
                    pendingUpdate = false;
                    setFieldDirty(
                        Boolean(inputRef.el && inputRef.el.value !== lastSetValue),
                    );
                }
            } else {
                inputRef.el.value = params.getValue();
                lastSetValue = inputRef.el.value;
                setFieldDirty(
                    Boolean(inputRef.el && inputRef.el.value !== lastSetValue),
                );
            }
        }
    }

    return inputRef;
}
