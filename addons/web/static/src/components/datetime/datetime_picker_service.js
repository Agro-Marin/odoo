// @ts-check
/** @odoo-module native */

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
 * @typedef {any} DateTime
 */
/**
 * @typedef {import("@web/components/datetime/datetime_picker").DateTimePickerProps} DateTimePickerProps
 * @typedef {import("@web/ui/popover/popover_hook").PopoverHookReturnType} PopoverHookReturnType
 * @typedef {import("@web/ui/popover/popover_service").PopoverServiceAddOptions} PopoverServiceAddOptions
 * @typedef {import("@odoo/owl").Component} Component
 * @typedef {ReturnType<typeof import("@odoo/owl").useRef>} OwlRef
 * @typedef {{
 * createPopover?: (component: Component, options: PopoverServiceAddOptions) => PopoverHookReturnType;
 * ensureVisibility?: () => boolean;
 * format?: string;
 * getInputs?: () => HTMLElement[];
 * onApply?: (value: DateTimePickerProps["value"]) => any;
 * onChange?: (value: DateTimePickerProps["value"]) => any;
 * onClose?: () => any;
 * pickerProps?: DateTimePickerProps;
 * showSeconds?: boolean;
 * target: HTMLElement | string;
 * useOwlHooks?: boolean;
 * }} DateTimePickerServiceParams
 * @typedef {{
 * enable: () => (() => void);
 * disable: () => boolean;
 * dispose: () => void;
 * isOpen: () => boolean;
 * open: (inputIndex: number) => void;
 * close: () => void;
 * commitInputs: () => Promise<void>;
 * state: DateTimePickerProps;
 * }} DateTimePickerHandle
 */

/**
 * @param {Record<string, any>} obj
 * @returns {Record<string, any>}
 */
function markValuesRaw(obj) {
    /** @type {Record<string, any>} */
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
const parsers = {
    date: parseDate,
    datetime: parseDateTime,
};

export class DateTimePickerController {
    /**
     * @param {Partial<DateTimePickerServiceParams>} params
     * @param {any} env
     * @param {any} popoverService
     * @param {Set<DateTimePickerHandle>} dateTimePickerList
     */
    constructor(params, env, popoverService, dateTimePickerList) {
        this.params = params;
        this.env = env;
        this.popoverService = popoverService;
        this.dateTimePickerList = dateTimePickerList;

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

        this.createPopover =
            params.createPopover ||
            /** @type {(...args: any[]) => PopoverHookReturnType} */ (
                (/** @type {any} */ component, /** @type {any} */ options) =>
                    makePopover(
                        (/** @type {any[]} */ ...args) =>
                            /** @type {any} */ (popoverService).add(...args),
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

        /** @type {DateTimePickerHandle} */
        this.picker = {
            enable: this.enable,
            disable: () => this.dateTimePickerList.delete(this.picker),
            dispose: this.dispose,
            isOpen: this.isOpen,
            open: this.open,
            close: () => this.popover.close(),
            commitInputs: this.commitInputs,
            state: this.pickerProps,
        };
        this.dateTimePickerList.add(this.picker);
    }

    onPickerPropsUpdated = () => {
        for (const [el, value] of zip(
            this.getInputs(),
            ensureArray(this.pickerProps.value),
            true,
        )) {
            if (el) {
                this.updateInput(/** @type {HTMLInputElement} */ (el), value);
            }
        }

        if (!this.isOpen()) {
            this.apply();
        }

        this.shouldFocus = true;
    };

    releaseTargetMargin = () => {
        this.restoreTargetMargin?.();
        this.restoreTargetMargin = null;
    };

    onPopoverClose = async () => {
        this.releaseTargetMargin();
        if (this.destroyed) {
            return;
        }
        this.updateValueFromInputs();
        this.setFocusClass(null);
        await this.apply();
        this.params.onClose?.();
    };

    apply = async () => {
        if (this.destroyed) {
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

    commitInputs = async () => {
        if (this.destroyed) {
            return;
        }
        this.updateValueFromInputs();
        await this.apply();
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
            if (inputEl && !inputEl.disabled && !inputEl.readOnly) {
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
            for (const [el, event, handler] of addedListeners.splice(0)) {
                el.removeEventListener(event, handler);
            }
        };
        this.disableListeners = removeListeners;
        return removeListeners;
    };

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
     * Which of the two inputs an event came from. Anything that is not the end
     * input counts as the start one, which is what a single-input picker needs.
     * @param {EventTarget | null} el
     * @returns {0 | 1}
     */
    indexOfInput = (el) => (el === this.getInput(1) ? 1 : 0);

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
            const inputEls = this.getInputs().filter(Boolean);
            while (parentElement) {
                const candidate = parentElement;
                if (inputEls.every((inputEl) => candidate.contains(inputEl))) {
                    break;
                }
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
     * @param {Event} ev
     */
    onInputChange = (ev) => {
        this.updateValueFromInputs();
        this.inputsChanged[this.indexOfInput(ev.target)] = true;
        if (!this.isOpen() || this.inputsChanged.every(Boolean)) {
            this.saveAndClose();
        }
    };

    /**
     * @param {Event} ev
     */
    onInputClick = (ev) => {
        this.open(this.indexOfInput(ev.target));
    };

    /**
     * @param {FocusEvent} ev
     */
    onInputFocus = (ev) => {
        const target = /** @type {HTMLInputElement} */ (ev.target);
        this.pickerProps.focusedDateIndex = this.indexOfInput(target);
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
            return this.open(this.indexOfInput(ev.target));
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
     * @param {number} inputIndex
     */
    open = (inputIndex) => {
        this.pickerProps.focusedDateIndex = inputIndex;

        if (!this.isOpen()) {
            const popoverTarget = this.getPopoverTarget();
            if (!popoverTarget) {
                return;
            }
            if (this.ensureVisibility()) {
                const { marginBottom } = popoverTarget.style;
                popoverTarget.style.marginBottom = `100vh`;
                popoverTarget.scrollIntoView(true);
                this.restoreTargetMargin = () => {
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

    saveAndClose = () => {
        if (this.isOpen()) {
            this.popover.close();
        } else {
            this.apply();
        }
    };

    /**
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
     * @param {HTMLInputElement} inputEl
     */
    setInputFocus = (inputEl) => {
        inputEl.selectionStart = 0;
        inputEl.selectionEnd = inputEl.value.length;

        this.setFocusClass(inputEl);

        this.shouldFocus = false;
    };

    /**
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

        let nextFocusedDateIndex = this.pickerProps.focusedDateIndex;
        if (
            this.pickerProps.range &&
            Array.isArray(value) &&
            unit !== "time" &&
            source === "picker"
        ) {
            if (!value[0]) {
                nextFocusedDateIndex = 0;
            } else if (
                this.pickerProps.focusedDateIndex === 0 ||
                (value[1] && value[1] < value[0])
            ) {
                const focused = value[this.pickerProps.focusedDateIndex];
                if (focused) {
                    const { year, month, day } = focused;
                    value = /** @type {any} */ (
                        value.map((bound) => bound && bound.set({ year, month, day }))
                    );
                }
                nextFocusedDateIndex = 1;
            } else {
                nextFocusedDateIndex = this.pickerProps.focusedDateIndex === 1 ? 0 : 1;
            }
        }

        this.pickerProps.value = value;
        this.pickerProps.focusedDateIndex = nextFocusedDateIndex;

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

    dispose = () => {
        this.destroyed = true;
        this.popover.close();
        this.releaseTargetMargin();
        this.disableListeners?.();
        this.dateTimePickerList.delete(this.picker);
    };

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

    focusIfNeeded = () => {
        if (this.isOpen() && this.shouldFocus) {
            this.focusActiveInput();
        }
    };
}

/**
 * Hands out {@link DateTimePickerHandle}s and keeps the set of live ones, so that
 * opening any picker closes the others.
 */
export class DateTimePickerService {
    /**
     * @param {any} env
     * @param {any} popoverService
     */
    constructor(env, popoverService) {
        this.env = env;
        this.popoverService = popoverService;
        /** @type {Set<DateTimePickerHandle>} */
        this.dateTimePickerList = new Set();
    }

    /**
     * @param {Partial<DateTimePickerServiceParams>} [params]
     * @returns {DateTimePickerHandle}
     */
    create(params = {}) {
        const controller = new DateTimePickerController(
            params,
            this.env,
            this.popoverService,
            this.dateTimePickerList,
        );

        if (params.useOwlHooks) {
            onWillDestroy(() => controller.dispose());

            if (typeof params.target === "string") {
                controller.targetRef = useRef(params.target);
            }

            onWillRender(controller.computeBasePickerProps);

            useEffect(controller.enable, controller.getInputs);

            onPatched(controller.focusIfNeeded);
        } else if (typeof params.target === "string") {
            throw new Error(
                `datetime picker service error: cannot use target as ref name when not using Owl hooks`,
            );
        }

        return controller.picker;
    }
}

const datetimePickerService = {
    dependencies: ["popover"],
    start(env, { popover: popoverService }) {
        return new DateTimePickerService(env, popoverService);
    },
};

registry.category("services").add("datetime_picker", datetimePickerService);
