// @ts-check
/** @odoo-module native */

/** @module @web/components/datetime/datetime_picker_service - Service managing date picker popover lifecycle, positioning, and input synchronization */

import {
    markRaw,
    onPatched,
    onWillDestroy,
    onWillRender,
    reactive,
    useEffect,
    useRef,
} from "@odoo/owl";
import { DateTimePicker } from "@web/components/datetime/datetime_picker";
import { DateTimePickerPopover } from "@web/components/datetime/datetime_picker_popover";
import {
    areDatesEqual,
    formatDate,
    formatDateTime,
    parseDate,
    parseDateTime,
} from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { ensureArray, zip, zipWith } from "@web/core/utils/collections/arrays";
import { shallowEqual } from "@web/core/utils/collections/objects";
import { makePopover } from "@web/ui/popover/popover_hook";

/**
 * @typedef {any} DateTime luxon DateTime instance — typed loosely because @types/luxon is not installed in this fork
 */
/**
 * @typedef {import("@web/components/datetime/datetime_picker").DateTimePickerProps} DateTimePickerProps
 * @typedef {import("@web/ui/popover/popover_hook").PopoverHookReturnType} PopoverHookReturnType
 * @typedef {import("@web/ui/popover/popover_service").PopoverServiceAddOptions} PopoverServiceAddOptions
 * @typedef {import("@odoo/owl").Component} Component
 * @typedef {ReturnType<typeof import("@odoo/owl").useRef>} OwlRef
 *
 * @typedef {{
 *  createPopover?: (component: Component, options: PopoverServiceAddOptions) => PopoverHookReturnType;
 *  ensureVisibility?: () => boolean;
 *  format?: string;
 *  getInputs?: () => HTMLElement[];
 *  onApply?: (value: DateTimePickerProps["value"]) => any;
 *  onChange?: (value: DateTimePickerProps["value"]) => any;
 *  onClose?: () => any;
 *  pickerProps?: DateTimePickerProps;
 *  showSeconds?: boolean;
 *  target: HTMLElement | string;
 *  useOwlHooks?: boolean;
 * }} DateTimePickerServiceParams
 *
 * @typedef {{
 *  enable: () => (() => void);
 *  disable: () => boolean;
 *  dispose: () => void;
 *  isOpen: () => boolean;
 *  open: (inputIndex: number) => void;
 *  close: () => void;
 *  state: DateTimePickerProps;
 * }} DateTimePicker
 */

/**
 * @template {object} T
 * @param {T} obj
 */
function markValuesRaw(obj) {
    /** @type {any} */
    const copy = {};
    for (const [key, value] of Object.entries(obj)) {
        if (value && typeof value === "object") {
            copy[key] = markRaw(value);
        } else {
            copy[key] = value;
        }
    }
    return copy;
}

/**
 * @param {Record<string, any>} props
 */
function stringifyProps(props) {
    const copy = {};
    for (const [key, value] of Object.entries(props)) {
        copy[key] = JSON.stringify(value);
    }
    return copy;
}

const FOCUS_CLASSNAME = "text-primary";

const formatters = {
    date: formatDate,
    datetime: formatDateTime,
};
const listenedElements = new WeakSet();
const parsers = {
    date: parseDate,
    datetime: parseDateTime,
};

/**
 * Plain (mount-free) controller holding the whole picker lifecycle: input DOM
 * synchronization, popover open/close, and value marking/applying. It is the
 * extraction of what used to be the `create()` closure — every field below is a
 * former closure local, every method a former inner function — so that the logic
 * can be unit-tested directly, without a full component mount.
 *
 * `create()` is now a thin adapter: it instantiates this controller and, when
 * `useOwlHooks` is set, wires the owl hooks (onWillDestroy / onWillRender /
 * useEffect / onPatched / useRef) around it. The returned `picker` API is
 * unchanged.
 *
 * Methods are arrow-function class fields on purpose: it preserves the closure's
 * lexical `this` and gives every DOM event handler a stable reference so
 * add/removeEventListener pair up (as the original bare inner functions did).
 */
export class DateTimePickerController {
    /**
     * @param {Partial<DateTimePickerServiceParams>} params
     * @param {any} env service env (exposes `isSmall`)
     * @param {any} popoverService
     * @param {Set<DateTimePicker>} dateTimePickerList service-lifetime registry of live pickers
     */
    constructor(params, env, popoverService, dateTimePickerList) {
        this.params = params;
        this.env = env;
        this.popoverService = popoverService;
        this.dateTimePickerList = dateTimePickerList;

        // Formerly the closure's shared mutable locals.
        /** @type {boolean[]} */
        this.inputsChanged = [];
        this.destroyed = false;
        /** @type {(() => void) | null} */
        this.disableListeners = null;
        this.lastAppliedStringValue = "";
        /** @type {(() => void) | null} */
        this.restoreTargetMargin = null;
        this.shouldFocus = false;
        /** @type {Record<string, any>} */
        this.stringProps = {};
        /** @type {OwlRef | null} */
        this.targetRef = null;

        // Formerly the closure-computed helpers (default or caller-provided).
        this.createPopover =
            params.createPopover ||
            /** @type {(...args: any[]) => PopoverHookReturnType} */ (
                (/** @type {any} */ component, /** @type {any} */ options) =>
                    makePopover(
                        /** @type {any} */ (popoverService).add,
                        component,
                        options,
                    )
            );
        this.ensureVisibility = params.ensureVisibility || (() => this.env.isSmall);
        this.getInputs = params.getInputs || (() => [this.getTarget(), null]);

        /** @type {any} */
        const rawPickerProps = {
            ...DateTimePicker.defaultProps,
            onReset: () => {
                this.updateValue(
                    ensureArray(this.pickerProps.value).length === 2
                        ? [false, false]
                        : false,
                    "date",
                    "picker",
                );
                this.saveAndClose();
            },
            onSelect: (/** @type {any} */ value, /** @type {any} */ unit) => {
                value &&= markRaw(value);
                this.updateValue(value, unit, "picker");
                if (!this.pickerProps.range && this.pickerProps.type === "date") {
                    this.saveAndClose();
                }
            },
            ...markValuesRaw(params.pickerProps || {}),
        };
        this.pickerProps = reactive(rawPickerProps, () => this.onPickerPropsUpdated());
        this.popover = this.createPopover(/** @type {any} */ (DateTimePickerPopover), {
            onClose: () => this.onPopoverClose(),
        });

        /** @type {DateTimePicker} */
        this.picker = {
            enable: this.enable,
            disable: () => this.dateTimePickerList.delete(this.picker),
            dispose: this.dispose,
            isOpen: this.isOpen,
            open: this.open,
            close: () => this.popover.close(),
            state: this.pickerProps,
        };
        this.dateTimePickerList.add(this.picker);
    }

    /**
     * Reactivity callback fired whenever `pickerProps` changes: syncs every
     * input with the new value and, when the popover is closed, applies eagerly.
     */
    onPickerPropsUpdated = () => {
        // Update inputs
        for (const [el, value] of zip(
            this.getInputs(),
            ensureArray(this.pickerProps.value),
            true,
        )) {
            if (el) {
                this.updateInput(/** @type {HTMLInputElement} */ (el), value);
                // Apply changes immediately if the popover is already closed.
                // Otherwise ´apply()´ will be called later on close.
                if (!this.isOpen()) {
                    this.apply();
                }
            }
        }

        this.shouldFocus = true;
    };

    /**
     * Popover "onClose" handler: commits the current input values and applies
     * them, unless the owner was destroyed first (see `destroyed` guard).
     */
    onPopoverClose = async () => {
        if (this.destroyed) {
            // The owner was destroyed (its onWillDestroy ran first and set the
            // flag). Skip the whole close handler: neither the input sync
            // (onChange) nor apply (onApply) must run against a gone owner —
            // same guard usePopover applies via `status()`.
            return;
        }
        this.updateValueFromInputs();
        this.setFocusClass(null);
        this.restoreTargetMargin?.();
        this.restoreTargetMargin = null;
        await this.apply();
        this.params.onClose?.();
    };

    /**
     * Wrapper method on the "onApply" callback to only call it when the
     * value has changed, and set other internal variables accordingly.
     */
    apply = async () => {
        if (this.destroyed) {
            // The owner component has been destroyed. A popover
            // torn down during that teardown (e.g. by its
            // target-removal observer, or our own close()) must not
            // apply against the now-gone component/record.
            return;
        }
        const { value } = this.pickerProps;
        const stringValue = JSON.stringify(value);
        if (
            stringValue === this.lastAppliedStringValue ||
            stringValue === this.stringProps.value
        ) {
            return;
        }

        this.lastAppliedStringValue = stringValue;
        this.inputsChanged = ensureArray(value).map(() => false);

        await this.params.onApply?.(value);

        this.stringProps.value = stringValue;
    };

    enable = () => {
        /** @type {Array<[Element, string, (ev: any) => void]>} */
        const addedListeners = [];
        this.disableListeners?.();
        for (const [el, value] of zip(
            this.getInputs(),
            ensureArray(this.pickerProps.value),
            true,
        )) {
            const inputEl = /** @type {HTMLInputElement} */ (el);
            this.updateInput(inputEl, value);
            if (
                inputEl &&
                !inputEl.disabled &&
                !inputEl.readOnly &&
                !listenedElements.has(inputEl)
            ) {
                listenedElements.add(inputEl);
                inputEl.addEventListener("change", this.onInputChange);
                inputEl.addEventListener("click", this.onInputClick);
                inputEl.addEventListener("focus", this.onInputFocus);
                inputEl.addEventListener("keydown", this.onInputKeydown);
                addedListeners.push(
                    [inputEl, "change", this.onInputChange],
                    [inputEl, "click", this.onInputClick],
                    [inputEl, "focus", this.onInputFocus],
                    [inputEl, "keydown", this.onInputKeydown],
                );
            }
        }
        const calendarIconGroupEl = this.getInput(0)?.parentElement?.querySelector(
            ".o_input_group_date_icon",
        );
        const onCalendarIconClick = () => this.open(0);
        if (calendarIconGroupEl) {
            calendarIconGroupEl.classList.add("cursor-pointer");
            calendarIconGroupEl.addEventListener("click", onCalendarIconClick);
            addedListeners.push([calendarIconGroupEl, "click", onCalendarIconClick]);
        }
        const removeListeners = () => {
            if (this.disableListeners === removeListeners) {
                this.disableListeners = null;
            }
            for (const [el, event, handler] of addedListeners) {
                el.removeEventListener(event, handler);
                listenedElements.delete(el);
            }
        };
        this.disableListeners = removeListeners;
        return removeListeners;
    };

    /**
     * Ensures the current focused input (indicated by `pickerProps.focusedDateIndex`)
     * is actually focused.
     */
    focusActiveInput = () => {
        const inputEl = this.getInput(this.pickerProps.focusedDateIndex);
        if (!inputEl) {
            this.shouldFocus = true;
            return;
        }

        const { activeElement } = inputEl.ownerDocument;
        if (activeElement !== inputEl) {
            inputEl.focus();
        }
        this.setInputFocus(inputEl);
    };

    /**
     * @param {number} valueIndex
     * @returns {HTMLInputElement | null}
     */
    getInput = (valueIndex) => {
        const el = /** @type {HTMLInputElement} */ (this.getInputs()[valueIndex]);
        if (el?.isConnected) {
            return el;
        }
        return null;
    };

    /**
     * Returns the appropriate root element to attach the popover:
     * - if the value is a range: the closest common parent of the two inputs
     * - if not: the first input
     */
    getPopoverTarget = () => {
        const target = this.getTarget();
        if (target) {
            return target;
        }
        if (this.pickerProps.range) {
            const firstInput = this.getInput(0);
            if (!firstInput) {
                return this.getInput(1) ?? this.getTarget();
            }
            let parentElement = firstInput.parentElement;
            const inputEls = this.getInputs();
            while (
                parentElement &&
                !inputEls.every((inputEl) => parentElement.contains(inputEl))
            ) {
                parentElement = parentElement.parentElement;
            }
            return parentElement || firstInput;
        } else {
            return this.getInput(0);
        }
    };

    /**
     * @returns {HTMLElement | null}
     */
    getTarget = () =>
        this.targetRef
            ? /** @type {HTMLElement | null} */ (this.targetRef.el)
            : /** @type {HTMLElement} */ (this.params.target);

    isOpen = () => this.popover.isOpen;

    /**
     * Inputs "change" event handler. This will trigger an "onApply" callback if
     * one of the following is true:
     * - there is only one input;
     * - the popover is closed;
     * - the other input has also changed.
     *
     * @param {Event} ev
     */
    onInputChange = (ev) => {
        this.updateValueFromInputs();
        const inputTarget = /** @type {HTMLInputElement} */ (ev.target);
        this.inputsChanged[inputTarget === this.getInput(1) ? 1 : 0] = true;
        if (!this.isOpen() || this.inputsChanged.every(Boolean)) {
            this.saveAndClose();
        }
    };

    /**
     * @param {Event} ev
     */
    onInputClick = (ev) => {
        const target = /** @type {HTMLInputElement} */ (ev.target);
        this.open(target === this.getInput(1) ? 1 : 0);
    };

    /**
     * @param {FocusEvent} ev
     */
    onInputFocus = (ev) => {
        const target = /** @type {HTMLInputElement} */ (ev.target);
        this.pickerProps.focusedDateIndex = target === this.getInput(1) ? 1 : 0;
        this.setInputFocus(target);
    };

    /**
     * @param {KeyboardEvent} ev
     */
    onInputKeydown = (ev) => {
        const inputTarget = /** @type {HTMLInputElement} */ (ev.target);
        if (ev.key === "Enter" && ev.ctrlKey) {
            ev.preventDefault();
            this.updateValueFromInputs();
            return this.open(inputTarget === this.getInput(1) ? 1 : 0);
        }
        switch (ev.key) {
            case "Enter":
            case "Escape": {
                return this.saveAndClose();
            }
            case "Tab": {
                if (
                    !this.getInput(0) ||
                    !this.getInput(1) ||
                    inputTarget !== this.getInput(ev.shiftKey ? 1 : 0)
                ) {
                    return this.saveAndClose();
                }
                break;
            }
        }
    };

    /**
     * @param {number} inputIndex Input from which to open the picker
     */
    open = (inputIndex) => {
        this.pickerProps.focusedDateIndex = inputIndex;

        if (!this.isOpen()) {
            const popoverTarget = this.getPopoverTarget();
            if (this.ensureVisibility()) {
                const { marginBottom } = popoverTarget.style;
                // Adds enough space for the popover to be displayed below the target
                // even on small screens.
                popoverTarget.style.marginBottom = `100vh`;
                popoverTarget.scrollIntoView(true);
                this.restoreTargetMargin = async () => {
                    popoverTarget.style.marginBottom = marginBottom;
                };
            }
            for (const picker of this.dateTimePickerList) {
                picker.close();
            }
            this.popover.open(popoverTarget, { pickerProps: this.pickerProps });
        }

        this.focusActiveInput();
    };

    /**
     * @template {"format" | "parse"} T
     * @param {T} operation
     * @param {T extends "format" ? DateTime : string} value
     * @returns {[T extends "format" ? string : DateTime, null] | [null, Error]}
     */
    safeConvert = (operation, value) => {
        const { type } = this.pickerProps;
        const convertFn = (operation === "format" ? formatters : parsers)[type];
        /** @type {any} */
        const options = {
            tz: /** @type {any} */ (this.pickerProps).tz,
            format: this.params.format,
        };
        if (operation === "format") {
            options.showSeconds = this.params.showSeconds ?? true;
        }
        try {
            return [/** @type {any} */ (convertFn)(value, options), null];
        } catch (error) {
            if (error?.name === "ConversionError") {
                return [null, error];
            } else {
                throw error;
            }
        }
    };

    /**
     * Wrapper method to ensure the "onApply" callback is called, either:
     * - by closing the popover (if any);
     * - or by directly calling "apply", without updating the values.
     */
    saveAndClose = () => {
        if (this.isOpen()) {
            // apply will be done in the "onClose" callback
            this.popover.close();
        } else {
            this.apply();
        }
    };

    /**
     * Updates class names on given inputs according to the currently selected input.
     *
     * @param {HTMLInputElement | null} input
     */
    setFocusClass = (input) => {
        for (const el of this.getInputs()) {
            if (el) {
                el.classList.toggle(FOCUS_CLASSNAME, this.isOpen() && el === input);
            }
        }
    };

    /**
     * Applies class names to all inputs according to whether they are focused or not.
     *
     * @param {HTMLInputElement} inputEl
     */
    setInputFocus = (inputEl) => {
        inputEl.selectionStart = 0;
        inputEl.selectionEnd = inputEl.value.length;

        this.setFocusClass(inputEl);

        this.shouldFocus = false;
    };

    /**
     * Synchronizes the given input with the given value.
     *
     * @param {HTMLInputElement} el
     * @param {DateTime} value
     */
    updateInput = (el, value) => {
        if (!el) {
            return;
        }
        const [formattedValue] = this.safeConvert("format", value);
        el.value = formattedValue || "";
    };

    /**
     * @param {DateTimePickerProps["value"]} value
     * @param {"date" | "time"} unit
     * @param {"input" | "picker"} source
     */
    updateValue = (value, unit, source) => {
        if (source === "input" && areDatesEqual(this.pickerProps.value, value)) {
            return;
        }

        this.pickerProps.value = value;

        if (this.pickerProps.range && unit !== "time" && source === "picker") {
            if (!value[0]) {
                this.pickerProps.focusedDateIndex = 0;
            } else if (
                this.pickerProps.focusedDateIndex === 0 ||
                (value[0] && value[1] && value[1] < value[0])
            ) {
                // Selecting the first value, or a second value before the
                // first: sync the DATE (year/month/day) of all values to
                // the one just selected.
                const { year, month, day } = value[this.pickerProps.focusedDateIndex];
                for (let i = 0; i < value.length; i++) {
                    value[i] = value[i] && value[i].set({ year, month, day });
                }
                this.pickerProps.focusedDateIndex = 1;
            } else {
                // Selecting the second value after the first: toggle
                // the focus index.
                this.pickerProps.focusedDateIndex =
                    this.pickerProps.focusedDateIndex === 1 ? 0 : 1;
            }
        }

        this.params.onChange?.(value);
    };

    updateValueFromInputs = () => {
        const values = zipWith(
            this.getInputs(),
            ensureArray(this.pickerProps.value),
            (el, currentValue) => {
                if (!el || el.tagName?.toLowerCase() !== "input") {
                    return currentValue;
                }
                const inputEl = /** @type {HTMLInputElement} */ (el);
                const [parsedValue, error] = this.safeConvert("parse", inputEl.value);
                if (error) {
                    this.updateInput(inputEl, currentValue);
                    return currentValue;
                } else {
                    return parsedValue;
                }
            },
        );
        this.updateValue(values.length === 2 ? values : values[0], "date", "input");
    };

    /**
     * Full teardown: marks the picker destroyed (so the popover's
     * close handler no longer syncs/applies), closes the popover,
     * removes the input listeners added by `enable()` and releases
     * the service-lifetime registration. Auto-registered through
     * `onWillDestroy` when `useOwlHooks` is set; non-hook consumers
     * (public interactions) must call it in their cleanup or leak
     * a registration retaining their inputs on every restart.
     */
    dispose = () => {
        this.destroyed = true;
        this.popover.close();
        this.disableListeners?.();
        this.dateTimePickerList.delete(this.picker);
    };

    /**
     * onWillRender callback (hook mode): recomputes the base picker props from
     * the caller's (possibly getter-backed) `params.pickerProps` and pushes any
     * change into the reactive `pickerProps`.
     */
    computeBasePickerProps = () => {
        const nextProps = markValuesRaw(this.params.pickerProps || {});
        const oldStringProps = this.stringProps;

        this.stringProps = stringifyProps(nextProps);
        this.lastAppliedStringValue = this.stringProps.value;

        if (shallowEqual(oldStringProps, this.stringProps)) {
            return;
        }

        this.inputsChanged = ensureArray(nextProps.value).map(() => false);

        for (const [key, value] of Object.entries(nextProps)) {
            if (!areDatesEqual(this.pickerProps[key], value)) {
                this.pickerProps[key] = value;
            }
        }
    };

    /**
     * onPatched callback (hook mode): re-focuses the active input if the popover
     * is open and a focus was requested.
     */
    focusIfNeeded = () => {
        if (this.isOpen() && this.shouldFocus) {
            this.focusActiveInput();
        }
    };
}

export const datetimePickerService = {
    dependencies: ["popover"],
    start(env, { popover: popoverService }) {
        /** @type {Set<DateTimePicker>} */
        const dateTimePickerList = new Set();
        return {
            /**
             * Thin adapter over {@link DateTimePickerController}: instantiates
             * the controller and, in hook mode, wires the owl hooks around it.
             * The returned `picker` API is unchanged from before the extraction.
             *
             * @param {Partial<DateTimePickerServiceParams>} [params]
             */
            create(params = {}) {
                const controller = new DateTimePickerController(
                    params,
                    env,
                    popoverService,
                    dateTimePickerList,
                );

                if (params.useOwlHooks) {
                    // Registered before any onWillDestroy the caller adds, so the
                    // guard is set when a popover from the same destroy phase runs
                    // its close handler (OWL runs willDestroy in registration order).
                    onWillDestroy(() => controller.dispose());

                    if (typeof params.target === "string") {
                        controller.targetRef = useRef(params.target);
                    }

                    onWillRender(controller.computeBasePickerProps);

                    useEffect(controller.enable, controller.getInputs);

                    // Must be registered after `useEffect`: the effect may change
                    // input values that this patch callback then selects.
                    onPatched(controller.focusIfNeeded);
                } else if (typeof params.target === "string") {
                    throw new Error(
                        `datetime picker service error: cannot use target as ref name when not using Owl hooks`,
                    );
                }

                return controller.picker;
            },
        };
    },
};

registry.category("services").add("datetime_picker", datetimePickerService);
