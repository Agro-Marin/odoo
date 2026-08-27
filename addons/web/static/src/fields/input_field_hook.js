// @ts-check
/** @odoo-module native */

import { useComponent, useEffect, useRef } from "@odoo/owl";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { ModelEvent } from "@web/core/events";
import { ParseError } from "@web/core/parse_error";
import { useBus } from "@web/core/utils/hooks";
import { useFieldDirtySignal } from "@web/fields/field_dirty_signal";

/**
 * @typedef InputFieldContext
 * @property {any} component
 * @property {any} params
 * @property {{ el: HTMLInputElement | HTMLTextAreaElement | null }} inputRef
 * @property {string} fieldName
 * @property {() => boolean} shouldSave
 * @property {(isDirty: boolean) => void} setFieldDirty
 * @property {{
 * isDirty: boolean,
 * lastSetValue: string | null,
 * }} edit
 */

/**
 * @param {InputFieldContext} ctx
 */
function syncDirtyFromInput(ctx) {
    const { inputRef, edit } = ctx;
    ctx.setFieldDirty(Boolean(inputRef.el && inputRef.el.value !== edit.lastSetValue));
}

/**
 * @param {InputFieldContext} ctx
 * @param {boolean} [urgent]
 * @returns {Promise<void>}
 */
async function commitInputChanges(ctx, urgent) {
    const { component, params, inputRef, fieldName, edit } = ctx;
    if (!inputRef.el) {
        return;
    }

    if (urgent) {
        await commitUrgently(ctx);
        return;
    }

    edit.isDirty = inputRef.el.value !== edit.lastSetValue;
    if (!edit.isDirty) {
        return;
    }
    edit.isDirty = false;

    let value = inputRef.el.value;
    if (params.parse) {
        try {
            value = params.parse(value);
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

    const current = component.props.record.data[fieldName];
    if ((value ?? false) === (current ?? false)) {
        inputRef.el.value = params.getValue();
        edit.lastSetValue = inputRef.el.value;
        syncDirtyFromInput(ctx);
        return;
    }

    edit.lastSetValue = inputRef.el.value;
    try {
        await component.props.record.update(
            { [fieldName]: value },
            { save: ctx.shouldSave() },
        );
    } finally {
        syncDirtyFromInput(ctx);
    }
}

/**
 * @param {InputFieldContext} ctx
 * @returns {Promise<void>}
 */
async function commitUrgently(ctx) {
    const { component, params, inputRef, fieldName } = ctx;
    if (!inputRef.el) {
        return;
    }
    let value = inputRef.el.value;
    if (params.parse) {
        try {
            value = params.parse(value);
        } catch {
            return;
        }
    }
    if ((value ?? false) === (component.props.record.data[fieldName] ?? false)) {
        return;
    }
    await component.props.record.update({ [fieldName]: value }, { save: false });
}

/**
 * @param {InputFieldContext} ctx
 */
function bindInputListeners(ctx) {
    const { component, params, inputRef, fieldName, edit } = ctx;

    const onInput = (/** @type {any} */ ev) => {
        edit.isDirty = ev.target.value !== edit.lastSetValue;
        if (params.preventLineBreaks && ev.inputType === "insertFromPaste") {
            ev.target.value = ev.target.value.replace(/[\r\n]+/g, " ");
        }
        ctx.setFieldDirty(edit.isDirty);
        if (!component.props.record.isValid) {
            component.props.record.resetFieldValidity(fieldName);
        }
    };
    const onChange = () => commitInputChanges(ctx, false);
    const onKeydown = (/** @type {any} */ ev) => {
        const hotkey = getActiveHotkey(ev);
        const keys = ["tab", "shift+tab"];
        if (ev.target.tagName.toLowerCase() !== "textarea") {
            keys.push("enter");
        }
        if (keys.includes(hotkey)) {
            commitInputChanges(ctx, false);
        }
        if (params.preventLineBreaks && ["enter", "shift+enter"].includes(hotkey)) {
            ev.preventDefault();
        }
    };

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
}

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

    const fieldName = "fieldName" in params ? params.fieldName : component.props.name;
    if (!fieldName) {
        return inputRef;
    }

    /** @type {InputFieldContext} */
    const ctx = {
        component,
        params,
        inputRef,
        fieldName,
        shouldSave: params.shouldSave ?? (() => false),
        setFieldDirty: useFieldDirtySignal(),
        edit: { isDirty: false, lastSetValue: null },
    };

    bindInputListeners(ctx);

    useEffect(() => {
        const value = params.getValue();
        const el = inputRef.el;
        if (
            !el ||
            ctx.edit.isDirty ||
            component.props.record.isFieldInvalid(fieldName)
        ) {
            return;
        }
        if (el.value !== value) {
            const { selectionStart, selectionEnd, value: previousValue } = el;
            const wasFullySelected =
                selectionStart === 0 && selectionEnd === previousValue.length;
            el.value = value;
            if (wasFullySelected && document.activeElement === el) {
                el.select();
            }
        }
        ctx.edit.lastSetValue = el.value;
    });

    const { model } = component.props.record;
    useBus(model.bus, ModelEvent.WILL_SAVE_URGENTLY, (ev) => {
        ev.detail?.proms?.push(commitInputChanges(ctx, true));
    });
    useBus(model.bus, ModelEvent.NEED_LOCAL_CHANGES, (ev) => {
        ev.detail.proms.push(commitInputChanges(ctx));
    });

    return inputRef;
}
