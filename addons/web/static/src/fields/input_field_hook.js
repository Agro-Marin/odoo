// @ts-check
/** @odoo-module native */

/** @module @web/fields/input_field_hook - OWL hook that syncs an input element with the ORM record and handles dirty/parse/save lifecycle */

import { useComponent, useEffect, useRef } from "@odoo/owl";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { ModelEvent } from "@web/core/events";
import { useBus } from "@web/core/utils/hooks";

/**
 * This hook is meant to be used by field components that use an input or
 * textarea to edit their value. Its purpose is to prevent that value from being
 * erased by an update of the model (typically coming from an onchange) when the
 * user is currently editing it.
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
     * A field is dirty if it is no longer sync with the model
     * More specifically, a field is no longer dirty after it has *tried* to update the value in the model.
     * An invalid value will thefore not be dirty even if the model will not actually store the invalid value.
     */
    let isDirty = false;

    /**
     * The last value that has been commited to the model.
     * Not changed in case of invalid field value.
     */
    let lastSetValue = null;

    /**
     * Track the fact that there is a change sent to the model that hasn't been acknowledged yet
     * (e.g. because the onchange is still pending). This is necessary if we must do an urgent save,
     * as we have to re-send that change for the write that will be done directly.
     * FIXME: this could/should be handled by the model itself, when it will be rewritten
     */
    let pendingUpdate = false;

    /**
     * When a user types, we need to set the field as dirty.
     */
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
     * Uses the ORM falsy-empty convention (``?? false``) so that null/undefined
     * and ``false`` are treated as the same "empty" value. Both commit paths —
     * blur (``onChange``) and Tab/Enter/urgent (``commitChanges``) — share this
     * one predicate; previously ``onChange`` used a strict ``!==`` while
     * ``commitChanges`` used ``?? false``, so at the null-vs-false boundary blur
     * could fire a redundant ``record.update`` (and onchange RPC) that Tab/Enter
     * would not, or reset the input on one path but not the other.
     */
    function hasValueChanged(val) {
        return (val ?? false) !== (component.props.record.data[fieldName] ?? false);
    }

    /**
     * On blur, we consider the field no longer dirty, even if it were to be invalid.
     * However, if the field is invalid, the new value will not be committed to the model.
     *
     * Delegates to ``commitChanges`` so blur and Tab/Enter/urgent share a single
     * commit pipeline (parse → setInvalidField → hasValueChanged → update/reset).
     * The two used to be hand-maintained copies and drifted (see
     * ``hasValueChanged``). ``onInput`` maintains the invariant
     * ``isDirty ⇔ inputRef.el.value !== lastSetValue``, so the dirty recompute
     * inside ``commitChanges`` is equivalent to the old ``if (isDirty)`` guard.
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
     * Sometimes, a patch can happen with possible a new value for the field
     * If the user was typing a new value (isDirty) or the field is still invalid,
     * we need to do nothing.
     * If it is not such a case, we update the field with the new value.
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
            inputRef.el.value = value;
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
