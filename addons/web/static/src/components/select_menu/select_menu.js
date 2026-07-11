// @ts-check
/** @odoo-module native */

/** @module @web/components/select_menu/select_menu - Searchable dropdown select menu with multi-select tags and keyboard navigation */

import { Component, onWillUpdateProps, useEffect, useRef, useState } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { useDropdownState } from "@web/components/dropdown/dropdown_hooks";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { TagsList } from "@web/components/tags_list/tags_list";
import { hasTouch } from "@web/core/browser/feature_detection";
import { KeepLast } from "@web/core/utils/concurrency";
import { mergeClasses } from "@web/core/utils/dom/classname";
import { scrollTo } from "@web/core/utils/dom/scrolling";
import { useChildRef } from "@web/core/utils/hooks";
import { fuzzyLookup } from "@web/core/utils/search";
import { useDebounced } from "@web/core/utils/timing";
let selectMenuId = 0;

const collator = new Intl.Collator();

export const DEBOUNCED_DELAY = 250;

export class SelectMenu extends Component {
    static template = "web.SelectMenu";
    static choiceItemTemplate = "web.SelectMenu.ChoiceItem";

    static components = { Dropdown, DropdownItem, TagsList };

    static defaultProps = {
        value: undefined,
        id: "",
        name: "",
        class: "",
        menuClass: "",
        togglerClass: "",
        multiSelect: false,
        onSelect: () => {},
        onNavigated: () => {},
        onOpened: () => {},
        onClosed: () => {},
        required: false,
        searchable: true,
        autoSort: true,
        searchPlaceholder: "",
        choices: [],
        groups: [],
        sections: [],
        disabled: false,
    };

    static props = {
        choices: {
            optional: true,
            type: Array,
            element: {
                type: Object,
                shape: {
                    value: true,
                    label: { type: String },
                    "*": true,
                },
            },
        },
        groups: {
            type: Array,
            optional: true,
            element: {
                type: Object,
                shape: {
                    label: { type: String, optional: true },
                    choices: {
                        type: Array,
                        element: {
                            type: Object,
                            shape: {
                                value: true,
                                label: { type: String },
                                "*": true,
                            },
                        },
                    },
                    section: {
                        type: String,
                        optional: true,
                    },
                },
            },
        },
        sections: {
            type: Array,
            optional: true,
            element: {
                label: { type: String },
                name: { type: String },
            },
        },
        id: { type: String, optional: true },
        name: { type: String, optional: true },
        class: { type: String, optional: true },
        menuClass: { type: String, optional: true },
        togglerClass: { type: String, optional: true },
        required: { type: Boolean, optional: true },
        searchable: { type: Boolean, optional: true },
        autoSort: { type: Boolean, optional: true },
        placeholder: { type: String, optional: true },
        searchPlaceholder: { type: String, optional: true },
        searchClass: { type: String, optional: true },
        value: { optional: true },
        multiSelect: { type: Boolean, optional: true },
        onInput: { type: Function, optional: true },
        onSelect: { type: Function, optional: true },
        onNavigated: { type: Function, optional: true },
        onOpened: { type: Function, optional: true },
        onClosed: { type: Function, optional: true },
        slots: { type: Object, optional: true },
        disabled: { type: Boolean, optional: true },
        menuRef: { type: Function, optional: true },
    };

    static SCROLL_SETTINGS = {
        defaultCount: 500,
        increaseAmount: 300,
        distanceBeforeReload: 500,
    };

    setup() {
        this.selectMenuId = selectMenuId++;
        this.state = useState({
            choices: [],
            displayedOptions: [],
            searchValue: null,
            isFocused: false,
        });
        this.inputRef = useRef("inputRef");
        this.menuRef = useChildRef();
        this.onInputKeepLast = new KeepLast();
        this.onScrollListener = (ev) => this.onScroll(ev);
        this.scrollListenerEl = null;
        this.props.menuRef?.(this.menuRef);
        this.debouncedOnInput = useDebounced((searchString) => {
            if (!this.dropdownState.isOpen) {
                this.dropdownState.open();
            }
            this.onInput(searchString);
        }, DEBOUNCED_DELAY);
        this.dropdownState = useDropdownState();

        this.selectedChoice = this.getSelectedChoice(this.props);
        // Cache of props.choices sorted by label, keyed on the props.choices
        // array identity. filterOptions re-sorts ALL choices on every open;
        // for a stable choices array this recomputes an identical result each
        // time. Invalidate whenever the choices reference changes.
        /** @type {any[] | null} */
        this._sortedChoicesCache = null;
        /** @type {any[] | null} */
        this._sortedChoicesSource = null;
        onWillUpdateProps((nextProps) => {
            const choicesChanged = this.props.choices !== nextProps.choices;
            if (choicesChanged) {
                this.state.choices = nextProps.choices;
            }
            if (choicesChanged || this.props.value !== nextProps.value) {
                this.selectedChoice = this.getSelectedChoice(nextProps);
            }
        });
        useEffect(
            () => {
                if (this.dropdownState.isOpen) {
                    const groups = [
                        { choices: this.props.choices },
                        ...this.props.groups,
                    ];
                    this.filterOptions(this.state.searchValue, groups);
                }
            },
            () => [this.props.choices, this.props.groups],
        );

        this.navigationOptions = {
            shouldFocusFirstItem: !hasTouch(),
            virtualFocus: this.props.searchable,
            hotkeys: {
                enter: {
                    isAvailable: ({ navigator }) => navigator.items.length,
                    callback: (navigator) => {
                        if (navigator.activeItem) {
                            return navigator.activeItem.select();
                        }
                        if (
                            /** @type {HTMLInputElement} */ (document.activeElement)
                                .value
                        ) {
                            navigator.items[0].select();
                        }
                    },
                },
            },
            onItemActivated: (element) => {
                const index = Number.parseInt(element.dataset.choiceIndex, 10);
                if (index >= 0 && this.state.displayedOptions[index]) {
                    this.props.onNavigated(this.state.displayedOptions[index]);
                } else {
                    this.props.onNavigated();
                }
            },
        };
    }

    get displayValue() {
        return this.state.searchValue === null
            ? this.selectedChoice?.label || ""
            : this.state.searchValue;
    }

    get displayInputInToggler() {
        return !this.props.slots || !this.props.slots.default;
    }

    get displayInputInDropdown() {
        return (
            (this.isBottomSheet || !this.displayInputInToggler) && this.props.searchable
        );
    }

    get isBottomSheet() {
        return this.env.isSmall && hasTouch();
    }

    get canDeselect() {
        if (this.props.required) {
            return false;
        }
        if (this.props.multiSelect) {
            return this.selectedChoice.length > 0;
        }
        return this.selectedChoice !== undefined;
    }

    get multiSelectChoices() {
        return this.selectedChoice.map((c) => ({
            id: c.value,
            text: c.label,
            onDelete: () => {
                const values = [...this.props.value];
                values.splice(values.indexOf(c.value), 1);
                this.props.onSelect(values);
            },
        }));
    }

    get menuClass() {
        return mergeClasses(
            {
                "my-0": this.displayInputInToggler,
                o_select_menu_menu: true,
                o_select_menu_multi_select: this.props.multiSelect,
            },
            this.props.menuClass,
        );
    }

    get placeholderValue() {
        if (this.state.isFocused && this.props.searchPlaceholder) {
            return this.props.searchPlaceholder;
        }
        return this.props.placeholder;
    }

    async onBeforeOpen() {
        this.onInput("");
    }

    onInputFocus(ev) {
        if (!this.props.searchable) {
            return ev.target.blur();
        }
        if (ev.target.classList.contains("o_select_menu_input")) {
            this.state.isFocused = true;
            ev.target.select();
        }
    }

    onInputBlur(ev) {
        this.state.isFocused = false;
        if (ev.target.value === "" && !this.props.multiSelect) {
            if (this.canDeselect) {
                this.onInputClear();
            } else {
                this.state.searchValue = null;
            }
        }
    }

    onInputClick(ev) {
        if (!ev.target.classList.contains("o_select_menu_toggler")) {
            ev.stopPropagation();
        }
    }

    onSearchInput(ev) {
        this.state.searchValue = ev.target.value;
        this.debouncedOnInput(this.state.searchValue);
    }

    onInputClear() {
        // multiSelect consumers expect an array value, single-select a scalar.
        this.props.onSelect(this.props.multiSelect ? [] : null);
        this.dropdownState.close();
    }

    onStateChanged(open) {
        if (open) {
            if (this.isBottomSheet) {
                // the toggler input must not be focused
                /** @type {HTMLElement} */ (document.activeElement).blur();
            }
            if (this.displayInputInDropdown && !this.isBottomSheet) {
                this.inputRef.el.focus();
            }
            this.scrollListenerEl = /** @type {any} */ (this.menuRef).el ?? null;
            this.scrollListenerEl?.addEventListener("scroll", this.onScrollListener);
            const selectedElement = /** @type {any} */ (
                this.menuRef
            ).el?.querySelectorAll(".selected")[0];
            if (selectedElement) {
                scrollTo(selectedElement);
            }
            this.props.onOpened();
        } else {
            // A keystroke may have scheduled a debounced onInput that would
            // force the dropdown back open after a deliberate close (Escape,
            // selection): drop it.
            this.debouncedOnInput.cancel();
            this.scrollListenerEl?.removeEventListener("scroll", this.onScrollListener);
            this.scrollListenerEl = null;
            this.state.searchValue = null;
            this.props.onClosed();
        }
    }

    isOptionSelected(choice) {
        if (this.props.multiSelect) {
            return this.props.value.includes(choice.value);
        }
        return this.props.value === choice.value;
    }

    getItemClass(choice) {
        if (this.isOptionSelected(choice)) {
            return "o_select_menu_item fw-bolder selected";
        } else {
            return "o_select_menu_item";
        }
    }

    async onInput(searchString) {
        this.filterOptions(searchString);
        if (this.props.onInput) {
            await this.onInputKeepLast.add(
                Promise.resolve(this.props.onInput(searchString)),
            );
        }
    }

    getSelectedChoice(props) {
        const choices = [
            ...props.choices,
            ...props.groups.flatMap((g) => g.choices || []),
        ];
        if (!this.props.multiSelect) {
            return choices.find((c) => c.value === props.value);
        }

        const valueSet = new Set(props.value);
        // Combine previously selected choices + newly selected choice from
        // the searched choices, keep only the first occurrence of each value
        // and filter the choices based on props.value i.e. valueSet.
        const choiceByValue = new Map();
        for (const choice of [...(this.selectedChoice || []), ...choices]) {
            if (valueSet.has(choice.value) && !choiceByValue.has(choice.value)) {
                choiceByValue.set(choice.value, choice);
            }
        }
        return [...choiceByValue.values()];
    }

    onItemSelected(value) {
        if (this.props.multiSelect) {
            const values = [...this.props.value];
            const valueIndex = values.indexOf(value);

            if (valueIndex !== -1) {
                values.splice(valueIndex, 1);
                this.props.onSelect(values);
            } else {
                this.props.onSelect([...this.props.value, value]);
            }
        } else if (!this.selectedChoice || this.selectedChoice.value !== value) {
            this.props.onSelect(value);
        }
        this.state.searchValue = null;
    }

    // ==========================================================================================
    // #                                         Search                                         #
    // ==========================================================================================

    /**
     * Filters choices by ``searchString``, slicing the result to a
     * reasonable amount to avoid delay when opening the select.
     *
     * @param {String} searchString
     */
    filterOptions(searchString = "", groups) {
        const groupsList = groups || [
            { choices: this.props.choices, section: "" },
            ...this.props.groups,
        ];

        const _choices = [];
        const _sections = new Set();
        groupsList.sort((a, b) => collator.compare(a.section || "", b.section || ""));

        for (const group of groupsList) {
            let filteredOptions = group.choices || [];

            if (searchString) {
                filteredOptions = fuzzyLookup(
                    searchString.trim(),
                    filteredOptions,
                    (choice) => choice.label,
                );
            } else {
                if (this.props.autoSort) {
                    filteredOptions = this.getSortedChoices(filteredOptions);
                }
            }

            if (!filteredOptions.length) {
                continue;
            }
            if (group.section) {
                const section = this.props.sections.find(
                    (e) => e.name === group.section,
                );
                if (!_sections.has(section)) {
                    _sections.add(section);
                    _choices.push({ ...section, isGroup: true });
                }
            }
            if (group.label) {
                _choices.push({ ...group, isGroup: true });
            }
            _choices.push(...filteredOptions);
        }

        this.state.choices = _choices;
        this.sliceDisplayedOptions();
    }

    /**
     * Returns ``choices`` sorted by label. The result for ``props.choices``
     * (the common case: the same array is re-filtered on every open) is
     * cached against the array's identity so the sort runs once per distinct
     * choices reference instead of on every open. Other arrays (per-group
     * choices) are sorted without caching.
     *
     * @param {any[]} choices
     * @returns {any[]}
     */
    getSortedChoices(choices) {
        const sortByLabel = (a, b) => collator.compare(a.label, b.label);
        if (choices !== this.props.choices) {
            return choices.toSorted(sortByLabel);
        }
        if (this._sortedChoicesSource !== choices) {
            this._sortedChoicesSource = choices;
            this._sortedChoicesCache = choices.toSorted(sortByLabel);
        }
        return this._sortedChoicesCache;
    }

    // ==========================================================================================
    // #                                         Scroll                                         #
    // ==========================================================================================

    /**
     * Loads more choices as the user scrolls to the end of the dropdown.
     *
     * @param {*} event
     */
    onScroll(event) {
        const el = event.target;
        const hasReachMax =
            this.state.displayedOptions.length >= this.state.choices.length;
        const remainingDistance = el.scrollHeight - el.scrollTop;
        const distanceToReload =
            el.clientHeight +
            /** @type {any} */ (this.constructor).SCROLL_SETTINGS.distanceBeforeReload;

        if (!hasReachMax && remainingDistance < distanceToReload) {
            const displayCount =
                this.state.displayedOptions.length +
                /** @type {any} */ (this.constructor).SCROLL_SETTINGS.increaseAmount;

            this.state.displayedOptions = this.state.choices.slice(0, displayCount);
        }
    }

    /**
     * Sets ``displayedOptions`` so the selected choice is visible, showing
     * at least ``defaultCount`` options overall.
     */
    sliceDisplayedOptions() {
        const selectedIndex = this.getSelectedOptionIndex();
        const defaultCount = /** @type {any} */ (this.constructor).SCROLL_SETTINGS
            .defaultCount;

        if (selectedIndex === -1) {
            this.state.displayedOptions = this.state.choices.slice(0, defaultCount);
        } else {
            const endIndex = Math.max(
                selectedIndex +
                    /** @type {any} */ (this.constructor).SCROLL_SETTINGS
                        .increaseAmount,
                defaultCount,
            );
            this.state.displayedOptions = this.state.choices.slice(0, endIndex);
        }
    }

    getSelectedOptionIndex() {
        return this.state.choices.findIndex((choice) => this.isOptionSelected(choice));
    }
}
