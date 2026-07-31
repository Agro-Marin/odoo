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
        this.loadMoreSentinel = useRef("loadMoreSentinel");
        /** @type {IntersectionObserver | null} */
        this.loadMoreObserver = null;
        this.props.menuRef?.(this.menuRef);
        this.debouncedOnInput = useDebounced((searchString) => {
            if (!this.dropdownState.isOpen) {
                this.dropdownState.open();
            }
            this.onInput(searchString);
        }, DEBOUNCED_DELAY);
        this.dropdownState = useDropdownState();

        this.selectedChoice = this.getSelectedChoice(this.props);
        /** @type {WeakMap<any[], any[]> | null} */
        this._sortedChoicesCache = null;
        // Deliberately does NOT assign `state.choices`: that field holds the
        // list `filterOptions` builds (filtered, sorted, group headers folded
        // in), and seeding it with the raw prop let "No results" -- which reads
        // `state.choices` -- render on top of the options still listed from
        // `state.displayedOptions`. The effect below rebuilds both together.
        onWillUpdateProps((nextProps) => {
            if (
                this.props.choices !== nextProps.choices ||
                this.props.value !== nextProps.value
            ) {
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

    /**
     * The selected values, in multi-select mode. `value` is an optional prop,
     * so a multi-select consumer that has not supplied one yet must read as
     * "nothing selected" instead of throwing on `undefined.includes`.
     *
     * @returns {any[]}
     */
    get selectedValues() {
        return this.props.value ?? [];
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
                const values = [...this.selectedValues];
                const index = values.indexOf(c.value);
                if (index !== -1) {
                    values.splice(index, 1);
                    this.props.onSelect(values);
                }
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
        const menuEl = /** @type {any} */ (this.menuRef).el;
        const related = /** @type {Node | null} */ (ev.relatedTarget);
        if (this.dropdownState.isOpen && related && menuEl?.contains(related)) {
            return;
        }
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
        this.props.onSelect(this.props.multiSelect ? [] : null);
        this.dropdownState.close();
    }

    onStateChanged(open) {
        if (open) {
            if (this.isBottomSheet) {
                /** @type {HTMLElement} */ (document.activeElement).blur();
            }
            if (this.displayInputInDropdown && !this.isBottomSheet) {
                this.inputRef.el.focus();
            }
            this.observeLoadMore();
            const selectedElement = /** @type {any} */ (
                this.menuRef
            ).el?.querySelectorAll(".selected")[0];
            if (selectedElement) {
                scrollTo(selectedElement);
            }
            this.props.onOpened();
        } else {
            this.debouncedOnInput.cancel();
            this.loadMoreObserver?.disconnect();
            this.loadMoreObserver = null;
            this.state.searchValue = null;
            this.props.onClosed();
        }
    }

    isOptionSelected(choice) {
        // Group and section headers carry no `value`, so an unset `props.value`
        // would match them via `undefined === undefined` and report a header as
        // the selected option.
        if (choice.isGroup) {
            return false;
        }
        if (this.props.multiSelect) {
            return this.selectedValues.includes(choice.value);
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
        if (!props.multiSelect) {
            return choices.find((c) => c.value === props.value);
        }

        const valueSet = new Set(props.value ?? []);
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
            const values = [...this.selectedValues];
            const valueIndex = values.indexOf(value);

            if (valueIndex !== -1) {
                values.splice(valueIndex, 1);
                this.props.onSelect(values);
            } else {
                this.props.onSelect([...this.selectedValues, value]);
            }
        } else if (this.props.value !== value) {
            this.props.onSelect(value);
        }
        this.state.searchValue = null;
    }

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
        // Sections declared in `props.sections` are ordered as declared —
        // it is an ordered array, and its order was previously ignored in
        // favour of the section's technical name, which the user never sees.
        // Sections that were never declared keep the alphabetical fallback:
        // `section` doubles as a grouping key that works without any
        // `props.sections` at all, and then the name is the only order there is.
        const sectionRank = (group) => {
            if (!group.section) {
                return -1;
            }
            const index = this.props.sections.findIndex(
                (s) => s.name === group.section,
            );
            return index === -1 ? Infinity : index;
        };
        groupsList.sort((a, b) => {
            const rankA = sectionRank(a);
            const rankB = sectionRank(b);
            if (rankA !== rankB) {
                return rankA - rankB;
            }
            return collator.compare(a.section || "", b.section || "");
        });

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
     * Returns ``choices`` sorted by label, cached against the array's identity
     * so the n·log n sort runs once per distinct array reference instead of on
     * every open / every debounced keystroke-clear. A WeakMap keyed on the
     * array covers per-GROUP choices too (the previous single-slot cache only
     * covered ``props.choices``, so group-based consumers re-sorted every
     * group on every open — a visible latency cliff for large lists).
     *
     * @param {any[]} choices
     * @returns {any[]}
     */
    getSortedChoices(choices) {
        const sortByLabel = (a, b) => collator.compare(a.label, b.label);
        if (!this._sortedChoicesCache) {
            /** @type {WeakMap<any[], any[]>} */
            this._sortedChoicesCache = new WeakMap();
        }
        let sorted = this._sortedChoicesCache.get(choices);
        if (!sorted) {
            sorted = choices.toSorted(sortByLabel);
            this._sortedChoicesCache.set(choices, sorted);
        }
        return sorted;
    }

    /**
     * Load more choices as the end of the list comes within reach.
     *
     * A marker after the last option is watched instead of the scroll
     * position: the browser reports it approaching on its own, so a long list
     * no longer measures itself on every scroll frame. `distanceBeforeReload`
     * becomes the margin that decides how early "within reach" is.
     */
    observeLoadMore() {
        this.loadMoreObserver?.disconnect();
        const root = /** @type {any} */ (this.menuRef).el;
        const sentinel = this.loadMoreSentinel.el;
        if (!root || !sentinel) {
            return;
        }
        const { distanceBeforeReload, increaseAmount } = /** @type {any} */ (
            this.constructor
        ).SCROLL_SETTINGS;
        this.loadMoreObserver = new IntersectionObserver(
            ([entry]) => {
                if (!entry.isIntersecting) {
                    return;
                }
                if (this.state.displayedOptions.length >= this.state.choices.length) {
                    return;
                }
                this.state.displayedOptions = this.state.choices.slice(
                    0,
                    this.state.displayedOptions.length + increaseAmount,
                );
            },
            { root, rootMargin: `0px 0px ${distanceBeforeReload}px 0px` },
        );
        this.loadMoreObserver.observe(sentinel);
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
