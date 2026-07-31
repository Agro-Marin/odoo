// @ts-check
/** @odoo-module native */

/** @module @web/components/time_picker/time_picker */

import { Component, onWillUpdateProps, useRef, useState } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { useDropdownState } from "@web/components/dropdown/dropdown_hooks";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { parseTime, Time } from "@web/core/l10n/time";
import { mergeClasses } from "@web/core/utils/dom/classname";
import { uniqueId } from "@web/core/utils/functions";
import { useChildRef } from "@web/core/utils/hooks";

const HOURS = [...Array(24)].map((_, i) => i);
const MINUTES = [...Array(60)].map((_, i) => i);

/**
 * @typedef TimePickerProps
 * @property {string} [class=""]
 * @property {string|Time} [value]
 * @property {(value: Time) => any} [onChange]
 * @property {() => {}} [onInvalid]
 * @property {boolean} [showSeconds=false]
 * @property {number} [minutesRounding=5]
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

    setup() {
        /** @type {{ el: HTMLInputElement | null }} */
        this.inputRef = /** @type {any} */ (useRef("inputRef"));
        this.menuId = uniqueId("o_time_picker_menu_");
        this.menuRef = useChildRef();
        this.dropdownState = useDropdownState();

        this.state = useState({
            value: null,
            inputValue: "",
            isValid: true,
        });

        /** @type {Time[]} */
        this.suggestions = [];
        this.isNavigating = false;
        this.navigationOptions = this.getNavigationOptions();
        this.onPropsUpdated(this.props);

        onWillUpdateProps((nextProps) => this.onPropsUpdated(nextProps));
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
     * @returns {import("@web/services/navigation/navigation").NavigationOptions}
     */
    getNavigationOptions() {
        const handleArrow = (navigator) => {
            const value = this.suggestions[navigator.activeItemIndex];
            if (value) {
                this.state.inputValue = value.toString(this.props.showSeconds);
            }
        };

        return {
            virtualFocus: true,
            onUpdated: (navigator) => (this.navigator = navigator),
            hotkeys: {
                enter: {
                    bypassEditableProtection: true,
                    callback: (navigator) => {
                        if (!this.isNavigating) {
                            const value = parseTime(
                                this.inputRef.el.value,
                                this.props.showSeconds,
                            );
                            if (value) {
                                this.setValue(value);
                                this.close();
                            }
                        } else if (navigator.activeItem) {
                            /** @type {any} */ (navigator.activeItem).select();
                        }
                    },
                },
                tab: {
                    bypassEditableProtection: true,
                    callback: (navigator) => {
                        if (this.isNavigating && navigator.activeItemIndex >= 0) {
                            this.setValue(this.suggestions[navigator.activeItemIndex]);
                            this.close();
                        }
                    },
                },
                arrowdown: {
                    callback: (navigator) => {
                        navigator.next();
                        handleArrow(navigator);
                    },
                },
                arrowup: {
                    callback: (navigator) => {
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

        this.updateStateValue(Time.from(props.value));
    }

    /**
     * @param {TimePickerProps} props
     * @returns {number}
     */
    getSuggestionStep(props) {
        return props.minutesRounding <= 5 ? 15 : props.minutesRounding;
    }

    /**
     * @param {number} step
     * @returns {Time[]}
     */
    getSuggestions(step) {
        const suggestions = [];
        const minutes = MINUTES.filter((m) => !(m % step));
        for (const hour of HOURS) {
            for (const minute of minutes) {
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
        if (!value) {
            return 0;
        }
        const toMinutes = (time) => time.hour * 60 + time.minute + time.second / 60;
        const target = toMinutes(value);
        let nearestIndex = 0;
        let nearestDistance = Infinity;
        for (const [index, suggestion] of this.suggestions.entries()) {
            const distance = Math.abs(toMinutes(suggestion) - target);
            if (distance < nearestDistance) {
                nearestDistance = distance;
                nearestIndex = index;
            }
        }
        return nearestIndex;
    }

    /**
     * @param {Time|null} newValue
     * @param {boolean} [cleanValue=true]
     */
    setValue(newValue, cleanValue = true) {
        if (newValue && cleanValue) {
            newValue = newValue.copy();
            if (this.props.minutesRounding > 1) {
                newValue.roundMinutes(this.props.minutesRounding);
            }
            if (!this.props.showSeconds && this.state.value) {
                newValue.second = this.state.value.second;
            }
        }

        const lastValue = this.lastValue;
        this.updateStateValue(newValue);
        if (newValue && !newValue.equals(lastValue, this.props.showSeconds)) {
            this.props.onChange(newValue.copy());
        }
    }

    /**
     * @param {Time|null} newValue
     */
    updateStateValue(newValue) {
        if (
            newValue === this.lastValue ||
            newValue?.equals(this.lastValue, this.props.showSeconds)
        ) {
            return;
        }

        this.lastValue = newValue?.copy() ?? newValue;
        this.state.value = newValue;
        this.state.inputValue = newValue
            ? newValue.toString(this.props.showSeconds)
            : "";
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
     * @param {InputEvent} event
     */
    onInput(event) {
        this.ensureOpen();

        const value = parseTime(this.inputRef.el.value, this.props.showSeconds);
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
        const value = parseTime(this.inputRef.el.value, this.props.showSeconds);
        this.state.isValid = value !== null;
        if (this.state.isValid) {
            this.setValue(value);
            this.close();
        } else {
            this.props.onInvalid();
        }
    }

    /**
     * @param {KeyboardEvent} event
     */
    onKeydown(event) {
        this.isNavigating = ["arrowup", "arrowdown"].includes(getActiveHotkey(event));
    }

    /**
     * @param {{ selectAll?: boolean }} [options]
     */
    ensureOpen({ selectAll = false } = {}) {
        if (this.dropdownState.isOpen) {
            return;
        }
        this.isNavigating = false;
        this.dropdownState.open();
        if (selectAll) {
            this.inputRef.el.select();
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
