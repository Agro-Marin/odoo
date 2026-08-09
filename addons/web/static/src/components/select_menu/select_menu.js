// @ts-check
/** @odoo-module native */

/** @module @web/components/select_menu/select_menu */

import { Component, onWillRender, useRef, useState } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { useDropdownState } from "@web/components/dropdown/dropdown_hooks";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { TagsList } from "@web/components/tags_list/tags_list";
import { hasTouch } from "@web/core/browser/feature_detection";
import { KeepLast, SupersededError } from "@web/core/utils/concurrency";
import { mergeClasses } from "@web/core/utils/dom/classname";
import { scrollTo } from "@web/core/utils/dom/scrolling";
import { uniqueId } from "@web/core/utils/functions";
import { useChildRef } from "@web/core/utils/hooks";
import { fuzzyLookup } from "@web/core/utils/search";
import { useDebounced } from "@web/core/utils/timing";
import { utils } from "@web/ui/viewport";

const collator = new Intl.Collator();

const DEBOUNCED_DELAY = 250;

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
                type: Object,
                shape: {
                    label: { type: String },
                    name: { type: String },
                },
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
        this.selectMenuId = uniqueId("o_select_menu_");
        this.menuId = `${this.selectMenuId}_menu`;
        // The menu is the scroller, and it holds the search box, the empty
        // notice and the load-more marker as well as the choices. A listbox
        // owns options and nothing else, so the role goes on an inner element
        // wrapping only them -- and that, not the menu, is what the combobox
        // points `aria-controls` at.
        this.listboxId = `${this.selectMenuId}_listbox`;
        this.state = useState({
            choices: [],
            displayedOptions: [],
            // What is in the box, updated on every keystroke, versus the search
            // the menu is actually derived from, which only moves once the
            // debounce fires. Conflating the two would filter on each keystroke.
            searchValue: null,
            appliedSearch: "",
            isFocused: false,
        });
        this.inputRef = useRef("inputRef");
        this.menuRef = useChildRef();
        this.onInputKeepLast = new KeepLast({ rejectSuperseded: true });
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

        /** @type {Map<any, any>} */
        this._choiceMemory = new Map();
        /** @type {any[] | null} */
        this._choiceSignature = null;
        this.choicesRevision = 0;
        /** @type {any} */
        this.selectedChoice = undefined;
        /** @type {WeakMap<any[], { revision: number, sorted: any[] }>} */
        this._sortedChoicesCache = new WeakMap();

        onWillRender(() => {
            this._selectedValueSet = null;
            this.syncChoicesRevision();
            this.selectedChoice = this.getSelectedChoice(this.props);
            // The menu is derived from props that callers mutate in place, so it
            // has to be re-derived in the same pass that reads them. A
            // post-patch effect would leave the previous list on screen for a
            // frame, and would miss the mutation altogether whenever it did not
            // also change the identity of the array it happened in.
            if (this.dropdownState.isOpen && this._derivedKey !== this.derivationKey) {
                this.filterOptions(this.state.appliedSearch);
            }
        });

        const self = this;
        this.navigationOptions = {
            shouldFocusFirstItem: !hasTouch(),
            // A getter, not a value: `searchable` moves -- selection_field binds
            // it to `!isBottomSheet` -- and a menu that lost its search box has
            // nowhere to park a virtual cursor, so the navigator has to move
            // real focus again. Frozen, it left the arrow keys moving nothing.
            get virtualFocus() {
                return self.props.searchable;
            },
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
        return utils.isSmall() && hasTouch();
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

    onBeforeOpen() {
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
            this.state.appliedSearch = "";
            // Up to SCROLL_SETTINGS.defaultCount options were sliced out for a
            // menu that is gone; opening rebuilds them from the props.
            this.state.choices = [];
            this.state.displayedOptions = [];
            this._derivedKey = null;
            this.props.onClosed();
        }
    }

    /**
     * Membership is asked once per choice by filterOptions and again per choice
     * by every render, so a linear scan of the selection makes both quadratic.
     * The set is rebuilt once per pass rather than kept against the value's
     * identity: parents mutate reactive arrays in place, which leaves the
     * identity untouched and would serve a stale selection.
     *
     * @returns {Set<any>}
     */
    get selectedValueSet() {
        this._selectedValueSet ??= new Set(this.selectedValues);
        return this._selectedValueSet;
    }

    isOptionSelected(choice) {
        if (choice.isGroup) {
            return false;
        }
        if (this.props.multiSelect) {
            return this.selectedValueSet.has(choice.value);
        }
        return this.props.value === choice.value;
    }

    /**
     * `aria-selected` normally belongs to the navigation service, which uses it
     * for the cursor: that is the combobox convention, and it costs nothing
     * when one value is held, because the value itself is the text in the box.
     *
     * Several values cannot be, so in multi-select this attribute is the only
     * thing inside the listbox that can say which choices are held, and the
     * cursor has to give it up -- `aria-activedescendant` names the cursor
     * either way. Emitting it here is also what claims it: an item that
     * arrives with the attribute keeps it.
     *
     * @param {any} choice
     * @param {number} index
     * @returns {Record<string, any>}
     */
    getItemAttrs(choice, index) {
        const attrs = { "data-choice-index": index };
        if (this.props.multiSelect) {
            attrs["aria-selected"] = this.isOptionSelected(choice) ? "true" : "false";
        }
        return attrs;
    }

    getItemClass(choice) {
        if (this.isOptionSelected(choice)) {
            return "o_select_menu_item fw-bolder selected";
        } else {
            return "o_select_menu_item";
        }
    }

    async onInput(searchString) {
        // Moving the applied search is what makes the render below re-derive the
        // menu; filtering here too would just do the same work a second time.
        this.state.appliedSearch = searchString;
        if (this.props.onInput) {
            try {
                await this.onInputKeepLast.add(
                    Promise.resolve(this.props.onInput(searchString)),
                );
            } catch (error) {
                if (!(error instanceof SupersededError)) {
                    throw error;
                }
            }
        }
    }

    /**
     * Callers mutate the arrays they hand over in place, so neither `choices`
     * nor `groups` can be trusted to change identity when their contents do --
     * and neither can a choice, which callers edit field by field. Identity
     * alone therefore cannot answer "is the menu still derived from this?": an
     * edited label keeps its object, so a list sorted on the old spelling, or
     * filtered by a query the new one no longer matches, would stay on screen.
     *
     * Every field the derivation below actually reads goes into the signature.
     * That does two jobs: it subscribes this component to those fields -- the
     * template only reads the ones currently on screen, never the ones the
     * filter dropped -- and it turns a mutation into something a comparison
     * can see.
     */
    syncChoicesRevision() {
        const signature = [];
        const pushChoice = (choice) => {
            signature.push(choice, choice.label, choice.value);
        };
        for (const choice of this.props.choices) {
            pushChoice(choice);
        }
        for (const group of this.props.groups) {
            signature.push(group, group.label, group.section);
            for (const choice of group.choices || []) {
                pushChoice(choice);
            }
        }
        const previous = this._choiceSignature;
        if (
            !previous ||
            previous.length !== signature.length ||
            previous.some((entry, index) => entry !== signature[index])
        ) {
            this._choiceSignature = signature;
            this.choicesRevision++;
        }
    }

    getSelectedChoice(props) {
        // Grouped choices carry labels too, so a value whose choice only exists
        // under `groups` resolves to nothing until they are read.
        const choices = [
            ...props.choices,
            ...props.groups.flatMap((g) => g.choices || []),
        ];
        if (!props.multiSelect) {
            return choices.find((c) => c.value === props.value);
        }

        const values = /** @type {any[]} */ (props.value ?? []);
        const valueSet = new Set(values);
        // Searching narrows `choices` to what the server matched, so a value the
        // user already picked can drop out of it; remembering its choice is what
        // keeps the tag readable. Refreshing from the current choices first is
        // what lets a choice edited or replaced in place win over the memory.
        const refreshed = new Set();
        for (const choice of choices) {
            if (valueSet.has(choice.value) && !refreshed.has(choice.value)) {
                refreshed.add(choice.value);
                this._choiceMemory.set(choice.value, choice);
            }
        }
        for (const value of this._choiceMemory.keys()) {
            if (!valueSet.has(value)) {
                this._choiceMemory.delete(value);
            }
        }
        return values.map((value) => this._choiceMemory.get(value)).filter(Boolean);
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
     * Everything the displayed menu is derived from: the contents of the choices
     * (see syncChoicesRevision) and the search that has actually been applied.
     *
     * @returns {string}
     */
    get derivationKey() {
        return `${this.choicesRevision}\x00${this.state.appliedSearch}`;
    }

    /**
     * @param {String} searchString
     */
    filterOptions(searchString = "") {
        this._selectedValueSet = null;
        this._derivedKey = `${this.choicesRevision}\x00${searchString}`;
        const groupsList = [
            { choices: this.props.choices, section: "" },
            ...this.props.groups,
        ];

        const _choices = [];
        const _sections = new Set();
        // Ranking is asked once per group by the sort's comparator, i.e. more
        // than once per group; scanning `sections` each time makes ordering
        // quadratic in the number of sections.
        const sectionOrder = new Map(
            this.props.sections.map((section, index) => [section.name, index]),
        );
        const sectionRank = (group) => {
            if (!group.section) {
                return -1;
            }
            return sectionOrder.get(group.section) ?? Infinity;
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
                if (section && !_sections.has(section.name)) {
                    _sections.add(section.name);
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
     * @param {any[]} choices
     * @returns {any[]}
     */
    getSortedChoices(choices) {
        // The revision already covers every label the order depends on, so it
        // is the whole answer: comparing the entries again here would only
        // repeat a weaker version of that check -- one that a renamed choice
        // passes, because its object never moved.
        const cached = this._sortedChoicesCache.get(choices);
        if (cached && cached.revision === this.choicesRevision) {
            return cached.sorted;
        }
        const sorted = choices.toSorted((a, b) => collator.compare(a.label, b.label));
        this._sortedChoicesCache.set(choices, {
            revision: this.choicesRevision,
            sorted,
        });
        return sorted;
    }

    /** @returns {typeof SelectMenu.SCROLL_SETTINGS} */
    get scrollSettings() {
        return /** @type {typeof SelectMenu} */ (this.constructor).SCROLL_SETTINGS;
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

    sliceDisplayedOptions() {
        const selectedIndex = this.getSelectedOptionIndex();
        const { defaultCount, increaseAmount } = this.scrollSettings;

        if (selectedIndex === -1) {
            this.state.displayedOptions = this.state.choices.slice(0, defaultCount);
        } else {
            const endIndex = Math.max(selectedIndex + increaseAmount, defaultCount);
            this.state.displayedOptions = this.state.choices.slice(0, endIndex);
        }
    }

    getSelectedOptionIndex() {
        return this.state.choices.findIndex((choice) => this.isOptionSelected(choice));
    }
}
