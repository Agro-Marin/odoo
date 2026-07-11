// @ts-check
/** @odoo-module native */

/** @module @web/fields/input_field_hook - OWL hook that syncs an input element with the ORM record and handles dirty/parse/save lifecycle */

import { useComponent, useEffect, useRef } from "@odoo/owl";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { ModelEvent } from "@web/core/events";
import { useBus } from "@web/core/utils/hooks";

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
 * @param {string} [params.fieldName]
 * @param {() => boolean} [params.shouldSave] if true, save the record with the new value
 */
export function useInputField(params) {
    const inputRef = params.ref || useRef(params.refName || "input");
    const component = useComponent();
    const fieldName = params.fieldName || component.props.name;
    const shouldSave = params.shouldSave ?? (() => false);

    /*
     * A field is dirty if out of sync with the model. It stops being dirty once
     * it has *tried* to update the model, even if the value was invalid and thus
     * never actually stored.
     */
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
        component.props.record.model.bus.trigger(ModelEvent.FIELD_IS_DIRTY, isDirty);
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
        // We need to call getValue before the condition to always observe
        // the corresponding value in the record. Otherwise, in some cases,
        // if the value in the record change the useEffect isn't triggered.
        const value = params.getValue();
        // NB: unlike upstream, we deliberately do NOT reset `isDirty` when
        // `inputRef.el.value === value`. The fork commits on blur/Tab via
        // `onChange`/`commitChanges` (which clear `isDirty` themselves and set
        // `pendingUpdate`), so re-deriving dirtiness here would resync the
        // input to a stale model value while a slow onchange is still pending,
        // wiping what the user typed. See list_view slow-onchange tests.
        if (
            inputRef.el &&
            !isDirty &&
            !component.props.record.isFieldInvalid(fieldName)
        ) {
            if (inputRef.el.value !== value) {
                // Assign only on a genuine change: a same-value assignment
                // would needlessly collapse the user's selection. When the
                // rewrite happens on a fully-selected focused input (e.g. a
                // human_readable field reformatting "5k" -> "5000" right
                // after the focus handler's select-all), restore the
                // selection instead of leaving the caret at the end.
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
        // Re-commit synchronously (unchanged behaviour) AND expose the promise
        // so the urgent-save coordinator can await it before reading changes:
        // the re-commit's value must land in ``_changes`` before the sendBeacon
        // save serialises them.
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
                } catch {
                    if (!urgent) {
                        component.props.record.setInvalidField(fieldName);
                    }
                    return;
                }
            }

            if (hasValueChanged(val)) {
                lastSetValue = inputRef.el.value;
                pendingUpdate = true;
                // A rejected `update` (e.g. a failing onchange RPC) must not
                // leave `pendingUpdate` stuck at true and `FIELD_IS_DIRTY`
                // uncleared, so both are reset in `finally`.
                try {
                    await component.props.record.update(
                        { [fieldName]: val },
                        { save: shouldSave() },
                    );
                } finally {
                    pendingUpdate = false;
                    // Re-derive instead of hardcoding false: the user may
                    // have typed again while the update was pending, and
                    // clobbering that keystroke's FIELD_IS_DIRTY:true would
                    // show a "saved" status over uncommitted input.
                    component.props.record.model.bus.trigger(
                        ModelEvent.FIELD_IS_DIRTY,
                        Boolean(inputRef.el && inputRef.el.value !== lastSetValue),
                    );
                }
            } else {
                inputRef.el.value = params.getValue();
            }
        }
    }

    return inputRef;
}
