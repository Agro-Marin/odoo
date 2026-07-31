// @ts-check
/** @odoo-module native */

/** @module @web/fields/input_field_hook */

import { useComponent, useEffect, useRef } from "@odoo/owl";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { ModelEvent } from "@web/core/events";
import { ParseError } from "@web/core/parse_error";
import { useBus } from "@web/core/utils/hooks";
import { useFieldDirtySignal } from "@web/fields/field_dirty_signal";

/**
 * @param {Object} params
 * @param {() => string} params.getValue
 * @param {(value: string) => any} [params.parse]
 * @param {{ el: HTMLInputElement | HTMLTextAreaElement | null }} [params.ref]
 * @param {string} [params.refName="input"]
 * @param {boolean} [params.preventLineBreaks]
 * @param {string | null} [params.fieldName]
 * @param {() => boolean} [params.shouldSave]
 * @returns {{ el: HTMLInputElement | HTMLTextAreaElement | null }}
 */
export function useInputField(params) {
    const inputRef = params.ref || useRef(params.refName || "input");
    const component = useComponent();
    const shouldSave = params.shouldSave ?? (() => false);

    const fieldName = "fieldName" in params ? params.fieldName : component.props.name;
    if (!fieldName) {
        return inputRef;
    }
    const setFieldDirty = useFieldDirtySignal();

    let isDirty = false;

    let lastSetValue = null;

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

    function hasValueChanged(val) {
        return (val ?? false) !== (component.props.record.data[fieldName] ?? false);
    }

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
     * @param {boolean} [urgent]
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
