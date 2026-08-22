// @ts-check
/** @odoo-module native */

import { Component, onWillUpdateProps, useRef, useState } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { useDropdownState } from "@web/components/dropdown/dropdown_hook";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { parseTime, Time } from "@web/core/l10n/time";
import { mergeClasses } from "@web/core/utils/dom/classname";
import { uniqueId } from "@web/core/utils/functions";
import { useChildRef, useSyncedInputProperty } from "@web/core/utils/hooks";

const HOURS_PER_DAY = 24;
const MINUTES_PER_HOUR = 60;

/**
 * @typedef TimePickerProps
 * @property {string|Array|Object} [cssClass={}]
 * @property {string|Array|Object} [inputCssClass={}]
 * @property {string|Time|false|null} [value="00:00"]
 * @property {(value: Time) => any} [onChange]
 * @property {() => {}} [onInvalid]
 * @property {boolean} [showSeconds=false]
 * @property {number} [minutesRounding=5]
 * @property {string} [placeholder]
 */

export class TimePicker extends Component {
    static template = "web.TimePicker";
    static components = {
        Dropdown,
        DropdownItem,
    };
    static props = {
        cssClass: { type: [String, Array, Object], optional: true },
        inputCssClass: { type: [String, Array, Object], optional: true },
        value: {
            type: [String, Time, { value: false }, { value: null }],
            optional: true,
        },
        onChange: { type: Function, optional: true },
        onInvalid: { type: Function, optional: true },
        showSeconds: { type: Boolean, optional: true },
        minutesRounding: { type: Number, optional: true },
        placeholder: { type: String, optional: true },
    };
    static defaultProps = {
        cssClass: {},
        inputCssClass: {},
        value: "00:00",
        onChange: () => {},
        onInvalid: () => {},
        showSeconds: false,
        minutesRounding: 5,
    };

    /** @type {{ el: HTMLInputElement | null }} */
    inputRef;
    /** @type {string} */
    menuId;
    /** @type {any} */
    menuRef;
    /** @type {import("@web/components/dropdown/dropdown_hook").DropdownState} */
    dropdownState;
    /** @type {{ value: Time | null, inputValue: string, isValid: boolean }} */
    state;
    suggestions = [];
    navigatedValue = null;
    isDirty = false;
    /** @type {number | undefined} */
    suggestionsStep;
    /** @type {Time | null | undefined} */
    lastValue;
    /** @type {any} */
    navigator;
    /** @type {import("@web/core/navigation/navigation").NavigationOptions} */
    navigationOptions;

    setup() {
        this.inputRef = /** @type {any} */ (useRef("inputRef"));
        this.menuId = uniqueId("o_time_picker_menu_");
        this.menuRef = useChildRef();
        this.dropdownState = useDropdownState();

        this.state = useState({
            value: null,
            inputValue: "",
            isValid: true,
        });

        this.navigationOptions = this.getNavigationOptions();
        this.onPropsUpdated(this.props);

        onWillUpdateProps((nextProps) => this.onPropsUpdated(nextProps));
        useSyncedInputProperty(
            () => this.inputRef.el,
            () => this.state.inputValue,
        );
    }

    get cssClass() {
        return mergeClasses(this.props.cssClass, {
            o_time_picker_seconds: this.props.showSeconds,
        });
    }

    get inputCssClass() {
        return mergeClasses(this.props.inputCssClass, {
            o_invalid: !this.state.isValid,
        });
    }

    /**
     * @returns {import("@web/core/navigation/navigation").NavigationOptions}
     */
    getNavigationOptions() {
        const handleArrow = (/** @type {any} */ navigator) => {
            const value = this.suggestions[navigator.activeItemIndex];
            if (value) {
                this.navigatedValue = value;
                this.state.inputValue = value.toString(this.props.showSeconds);
            }
        };

        return {
            virtualFocus: true,
            onUpdated: (/** @type {any} */ navigator) => (this.navigator = navigator),
            hotkeys: {
                enter: {
                    bypassEditableProtection: true,
                    callback: () => {
                        if (this.commitNavigatedValue()) {
                            this.close();
                            return;
                        }
                        const value = parseTime(
                            this.inputRef.el?.value ?? "",
                            this.props.showSeconds,
                        );
                        if (value) {
                            this.setValue(value);
                            this.close();
                        }
                    },
                },
                tab: {
                    bypassEditableProtection: true,
                    callback: () => {
                        if (this.commitNavigatedValue()) {
                            this.close();
                        }
                    },
                },
                arrowdown: {
                    callback: (/** @type {any} */ navigator) => {
                        navigator.next();
                        handleArrow(navigator);
                    },
                },
                arrowup: {
                    callback: (/** @type {any} */ navigator) => {
                        navigator.previous();
                        handleArrow(navigator);
                    },
                },
            },
        };
    }

    /**
     * @param {TimePickerProps} props
     */
    onPropsUpdated(props) {
        const step = this.getSuggestionStep(props);
        if (step !== this.suggestionsStep) {
            this.suggestionsStep = step;
            this.suggestions = this.getSuggestions(step);
        }

        this.updateStateValue(Time.from(props.value), props);
    }

    /**
     * @param {TimePickerProps} props
     * @returns {number}
     */
    getSuggestionStep(props) {
        const rounding = props.minutesRounding ?? 5;
        return rounding <= 5 ? 15 : rounding;
    }

    /**
     * @param {number} step
     * @returns {number}
     */
    getSuggestionsPerHour(step) {
        return Math.ceil(MINUTES_PER_HOUR / step);
    }

    /**
     * @param {number} step
     * @returns {Time[]}
     */
    getSuggestions(step) {
        const suggestions = [];
        for (let hour = 0; hour < HOURS_PER_DAY; hour++) {
            for (let minute = 0; minute < MINUTES_PER_HOUR; minute += step) {
                suggestions.push(new Time({ hour, minute }));
            }
        }
        return suggestions;
    }

    /**
     * @param {Time|null} value
     * @returns {number}
     */
    getNearestSuggestionIndex(value) {
        if (!value || !this.suggestions.length) {
            return 0;
        }
        const step = /** @type {number} */ (this.suggestionsStep);
        const perHour = this.getSuggestionsPerHour(step);
        const target = value.hour * MINUTES_PER_HOUR + value.minute + value.second / 60;
        const withinHour = Math.min(
            Math.floor((value.minute + value.second / 60) / step),
            perHour - 1,
        );
        const floorIndex = Math.min(
            value.hour * perHour + withinHour,
            this.suggestions.length - 1,
        );
        const nextIndex = Math.min(floorIndex + 1, this.suggestions.length - 1);
        const distance = (/** @type {number} */ index) => {
            const suggestion = this.suggestions[index];
            return Math.abs(
                suggestion.hour * MINUTES_PER_HOUR + suggestion.minute - target,
            );
        };
        return distance(nextIndex) < distance(floorIndex) ? nextIndex : floorIndex;
    }

    /**
     * @param {Time|null} newValue
     */
    setValue(newValue) {
        if (newValue) {
            newValue = newValue.copy();
            if (this.props.minutesRounding > 1) {
                newValue.roundMinutes(this.props.minutesRounding);
            }
            if (!this.props.showSeconds && this.state.value) {
                newValue.second = this.state.value.second;
            }
        }

        const lastValue = this.lastValue;
        this.updateStateValue(newValue, this.props, true);
        if (newValue && !newValue.equals(lastValue, this.props.showSeconds)) {
            this.props.onChange(newValue.copy());
        }
    }

    /**
     * @param {Time|null} newValue
     * @param {TimePickerProps} [props]
     * @param {boolean} [force=false]
     */
    updateStateValue(newValue, props = this.props, force = false) {
        const rendered = newValue ? newValue.toString(props.showSeconds) : "";
        const isSameInstant =
            newValue === this.lastValue ||
            newValue?.equals(this.lastValue, props.showSeconds);

        this.lastValue = newValue?.copy() ?? newValue;
        this.state.value = newValue;

        if (
            this.state.inputValue !== rendered &&
            isSameInstant &&
            !force &&
            this.isDirty
        ) {
            return;
        }
        this.isDirty = false;
        this.state.inputValue = rendered;
        this.state.isValid = true;
    }

    /**
     * @param {Time} value
     */
    onItemSelected(value) {
        this.setValue(value);
        this.close();
    }

    /**
     * @returns {boolean}
     */
    commitNavigatedValue() {
        const value = this.navigatedValue;
        if (!value) {
            return false;
        }
        this.navigatedValue = null;
        this.setValue(value);
        return true;
    }

    onBlur() {
        this.commitNavigatedValue();
    }

    /**
     * @param {InputEvent} event
     */
    onInput(event) {
        this.ensureOpen();
        this.isDirty = true;
        this.navigatedValue = null;

        const value = parseTime(this.inputRef.el?.value ?? "", this.props.showSeconds);
        this.state.isValid = value !== null;

        if (!this.navigator) {
            return;
        }

        let index = -1;
        if (this.state.isValid) {
            index = this.suggestions.findIndex((s) => s.equals(value));
        }

        if (index === -1) {
            this.navigator.activeItem?.setInactive();
        } else {
            this.navigator.items[index]?.setActive();
        }
    }

    onChange() {
        const value = parseTime(this.inputRef.el?.value ?? "", this.props.showSeconds);
        this.state.isValid = value !== null;
        this.isDirty = false;
        this.navigatedValue = null;
        if (this.state.isValid) {
            this.setValue(value);
            this.close();
        } else {
            this.props.onInvalid();
        }
    }

    /**
     * @param {{ selectAll?: boolean }} [options]
     */
    ensureOpen({ selectAll = false } = {}) {
        if (this.dropdownState.isOpen) {
            return;
        }
        this.navigatedValue = null;
        this.dropdownState.open();
        if (selectAll) {
            this.inputRef.el?.select();
        }
    }

    close() {
        this.dropdownState.close();
    }

    /**
     * @returns {string}
     */
    getPlaceholder() {
        if (typeof this.props.placeholder === "string") {
            return this.props.placeholder;
        }
        const seconds = this.props.showSeconds ? ":ss" : "";
        return `hh:mm${seconds}`;
    }

    onDropdownOpened() {
        if (this.navigator) {
            const index = this.getNearestSuggestionIndex(this.state.value);
            this.navigator.items[index]?.setActive();
        }
    }
}
