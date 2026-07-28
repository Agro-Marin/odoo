// @ts-check
/** @odoo-module native */

/** @module @web/search/search_panel/search_panel - Sidebar filter panel with category trees and grouped checkbox filters */

import {
    Component,
    onWillStart,
    onWillUnmount,
    onWillUpdateProps,
    reactive,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { useSetupAction } from "@web/core/action_hook";
import { browser } from "@web/core/browser/browser";
import { SearchModelEvent } from "@web/core/events";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { useBus } from "@web/core/utils/hooks";

const isFilter = (s) => s.type === "filter";
const isActiveCategory = (s) => s.type === "category" && s.activeValueId;

/**
 * @param {Map<string | false, Object>} values
 * @returns {Object[]}
 */
const nameOfCheckedValues = (values) => {
    const names = [];
    for (const [, value] of values) {
        if (value.checked) {
            names.push(value.display_name);
        }
    }
    return names;
};

/**
 * Sidebar filter panel, divided into sections defined by a "<searchpanel>"
 * node inside the "<search>" arch. Each section holds categories or filter
 * values (grouped or ungrouped), driven by @see SearchModel.
 */
export class SearchPanel extends Component {
    static template = "web.SearchPanel";
    static props = {};
    static components = {
        Dropdown,
    };
    static subTemplates = {
        section: "web.SearchPanel.Section",
        category: "web.SearchPanel.Category",
        filtersGroup: "web.SearchPanel.FiltersGroup",
    };

    setup() {
        this.keyExpandSidebar = `search_panel_expanded,${this.env.config.viewId},${this.env.config.actionId}`;
        this.state = useState({
            active: {},
            expanded: {},
            sidebarExpanded: true,
        });
        this.hasImportedState = false;
        this.root = useRef("root");
        this.scrollTop = 0;
        this.dropdownStates = {};
        this.width = "10px";

        this.importState(this.env.searchPanelState);
        const sidebarExpandedPreference = browser.localStorage.getItem(
            this.keyExpandSidebar,
        );
        if (sidebarExpandedPreference !== null) {
            this.state.sidebarExpanded = exprToBoolean(sidebarExpandedPreference);
        }

        useBus(this.env.searchModel, SearchModelEvent.UPDATE, async () => {
            await this.env.searchModel.sectionsPromise;
            this.updateActiveValues();
            await this.render();
        });

        useEffect(
            (el) => {
                if (el && this.hasImportedState) {
                    el.style["min-width"] = this.width;
                    el.scroll({ top: this.scrollTop });
                }
            },
            () => [this.root.el],
        );

        useSetupAction({
            getGlobalState: () => ({
                searchPanel: this.exportState(),
            }),
        });

        onWillStart(async () => {
            await this.env.searchModel.sectionsPromise;
            this.expandDefaultValue();
            this.expandValues();
            this.updateActiveValues();
        });

        onWillUpdateProps(async () => {
            await this.env.searchModel.sectionsPromise;
            this.updateActiveValues();
        });

        onWillUnmount(() => {
            this._removeResizeListeners?.();
        });
    }

    /** @returns {Object[]} non-empty search panel sections from the search model */
    get sections() {
        return this.env.searchModel.getSections((s) => !s.empty);
    }

    /** @returns {string} JSON-serialized panel state (expanded nodes, scroll, width) */
    exportState() {
        const exported = {
            expanded: this.state.expanded,
            scrollTop: this.root.el?.scrollTop || 0,
            sidebarExpanded: this.state.sidebarExpanded,
            width: this.width,
        };
        return JSON.stringify(exported);
    }

    /** @param {Object|null} state - previously exported panel state, or null */
    importState(state) {
        this.hasImportedState = Boolean(state);
        if (this.hasImportedState) {
            this.state.expanded = state.expanded;
            this.scrollTop = state.scrollTop;
            this.state.sidebarExpanded = state.sidebarExpanded;
            this.width = state.width;
        }
    }

    /**
     * Get or create a reactive dropdown state for a section (mobile mode).
     * @param {number} sectionId
     * @returns {{ isOpen: boolean, open: Function, close: Function }}
     */
    getDropdownState(sectionId) {
        if (!this.dropdownStates[sectionId]) {
            const state = reactive({
                isOpen: false,
                open: () => (state.isOpen = true),
                close: () => (state.isOpen = false),
            });
            this.dropdownStates[sectionId] = state;
        }
        return this.dropdownStates[sectionId];
    }

    /**
     * Give every category an expansion map. Seeding is separate from computing
     * the default expansions because the latter is skipped for an imported
     * state, while the map itself is not optional: the Category template reads
     * `state.expanded[section.id][valueId]` for any value with children, and an
     * imported state only carries the categories that existed when it was
     * exported — `{}` when it was exported before the sections had loaded.
     */
    ensureExpansionState() {
        for (const category of this.env.searchModel.getSections(
            (s) => s.type === "category",
        )) {
            this.state.expanded[category.id] ??= {};
        }
    }

    /** Expand category values holding a category's default (active) value. */
    expandDefaultValue() {
        this.ensureExpansionState();
        if (this.hasImportedState) {
            return;
        }
        const categories = this.env.searchModel.getSections(
            (s) => s.type === "category",
        );
        for (const category of categories) {
            if (category.activeValueId) {
                const ancestorIds = this.getAncestorValueIds(
                    category,
                    category.activeValueId,
                );
                for (const ancestorId of ancestorIds) {
                    this.state.expanded[category.id][ancestorId] = true;
                }
            }
        }
    }

    /** Expand category tree nodes up to the configured `depth` level. */
    expandValues() {
        if (this.hasImportedState) {
            return;
        }
        const categories = this.env.searchModel.getSections(
            (s) => s.type === "category",
        );
        for (const category of categories) {
            if (category.depth === 0) {
                continue;
            }

            const expand = (id, level) => {
                if (!level) {
                    return;
                }
                this.state.expanded[category.id][id] = true;
                const { childrenIds } = category.values.get(id);
                level -= 1;
                for (const childId of childrenIds) {
                    expand(childId, level);
                }
            };

            for (const rootId of category.rootIds) {
                expand(rootId, category.depth);
            }
        }
    }

    /**
     * @param {Object} category
     * @param {number} categoryValueId
     * @returns {number[]} list of ids of the ancestors of the given value in
     *   the given category.
     */
    getAncestorValueIds(category, categoryValueId) {
        const { parentId } = category.values.get(categoryValueId);
        return parentId
            ? [...this.getAncestorValueIds(category, parentId), parentId]
            : [];
    }

    /**
     * Return active categories formatted for the control panel selection banner.
     * @returns {Object[]}
     */
    getCategorySelection() {
        const activeCategories = this.env.searchModel.getSections(isActiveCategory);
        const selection = [];
        for (const category of activeCategories) {
            const parentIds = this.getAncestorValueIds(
                category,
                category.activeValueId,
            );
            const orderedCategoryNames = [...parentIds, category.activeValueId].map(
                (valueId) => category.values.get(valueId).display_name,
            );
            selection.push({
                values: orderedCategoryNames,
                icon: category.icon,
                color: category.color,
            });
        }
        return selection;
    }

    /**
     * Return active filters formatted for the control panel selection banner.
     * @returns {Object[]}
     */
    getFilterSelection() {
        const filters = this.env.searchModel.getSections(isFilter);
        const selection = [];
        for (const { groups, values, icon, color } of filters) {
            let filterValues;
            if (groups) {
                filterValues = [...groups.values()]
                    .map((group) => nameOfCheckedValues(group.values))
                    .flat();
            } else if (values) {
                filterValues = nameOfCheckedValues(values);
            }
            if (filterValues.length) {
                selection.push({ values: filterValues, icon, color });
            }
        }
        return selection;
    }

    /**
     * Check whether the given section (or any section, if omitted) has an
     * active selection.
     * @param {Number} sectionId
     */
    hasSelection(sectionId = 0) {
        if (sectionId) {
            const sectionState = this.state.active[sectionId];
            if (sectionState instanceof Object) {
                return Object.values(sectionState).some((val) => val);
            }
            return Boolean(sectionState);
        }
        return Object.keys(this.state.active).some((key) =>
            this.hasSelection(/** @type {any} */ (key)),
        );
    }

    /**
     * Clear the active selection in the given section (or all sections, if
     * omitted).
     * @param {Number} sectionId
     */
    clearSelection(sectionId = 0) {
        const sectionIds = sectionId
            ? [sectionId]
            : Object.keys(this.state.active).map(Number);
        this.env.searchModel.clearSections(sectionIds);
    }

    /**
     * Prevent unnecessary calls to the model by ensuring a different category
     * is clicked.
     * @param {Object} category
     * @param {Object} value
     */
    async toggleCategory(category, value) {
        if (value.childrenIds.length) {
            const categoryState = this.state.expanded[category.id];
            if (categoryState[value.id] && category.activeValueId === value.id) {
                delete categoryState[value.id];
            } else {
                categoryState[value.id] = true;
            }
        } else {
            this.getDropdownState(category.id).close();
        }
        if (category.activeValueId !== value.id) {
            this.env.searchModel.toggleCategoryValue(category.id, value.id);
        }
    }

    /** Toggle sidebar expanded/collapsed and persist preference to localStorage. */
    toggleSidebar() {
        this._sidebarAutoCollapsed = false;
        this.state.sidebarExpanded = !this.state.sidebarExpanded;
        browser.localStorage.setItem(
            this.keyExpandSidebar,
            /** @type {any} */ (this.state.sidebarExpanded),
        );
    }

    /**
     * @param {number} filterId
     * @param {{ values: Map<Object> }} group
     */
    toggleFilterGroup(filterId, { values }) {
        const valueIds = [];
        const checked = [...values.values()].every(
            (value) => this.state.active[filterId][value.id],
        );
        values.forEach(({ id }) => {
            valueIds.push(id);
            this.state.active[filterId][id] = !checked;
        });
        this.env.searchModel.toggleFilterValues(filterId, valueIds, !checked);
    }

    /**
     * @param {number} filterId
     * @param {number} valueId
     * @param {{ currentTarget: HTMLInputElement }} event
     */
    toggleFilterValue(filterId, valueId, { currentTarget }) {
        this.state.active[filterId][valueId] = currentTarget.checked;
        this.env.searchModel.toggleFilterValues(filterId, [valueId]);
    }

    /**
     * Checked / indeterminate state of a filter group's header, derived from
     * the same `state.active` the value checkboxes render from.
     * @param {number} sectionId
     * @param {{ values: Map<any, Object> }} group
     * @returns {{ checked: boolean, indeterminate: boolean }}
     */
    getGroupState(sectionId, group) {
        const activeValues = this.state.active[sectionId] || {};
        let checkedCount = 0;
        for (const valueId of group.values.keys()) {
            if (activeValues[valueId]) {
                checkedCount++;
            }
        }
        return {
            checked: checkedCount > 0 && checkedCount === group.values.size,
            indeterminate: checkedCount > 0 && checkedCount < group.values.size,
        };
    }

    /** Sync component state with the SearchModel's current section values. */
    updateActiveValues() {
        const sections = this.sections;
        if (!sections.length) {
            if (this.state.sidebarExpanded) {
                this._sidebarAutoCollapsed = true;
                this.state.sidebarExpanded = false;
            }
        } else if (this._sidebarAutoCollapsed) {
            this._sidebarAutoCollapsed = false;
            this.state.sidebarExpanded = true;
        }
        for (const section of sections) {
            if (section.type === "category") {
                this.state.active[section.id] = section.activeValueId;
            } else {
                this.state.active[section.id] = {};
                if (section.groups) {
                    for (const group of section.groups.values()) {
                        for (const value of group.values.values()) {
                            this.state.active[section.id][value.id] = value.checked;
                        }
                    }
                }
                if (section?.values) {
                    for (const value of section.values.values()) {
                        this.state.active[section.id][value.id] = value.checked;
                    }
                }
            }
        }
    }

    /**
     * Start the sidebar resize drag.
     * @private
     * @param {PointerEvent} ev
     */
    _onStartResize(ev) {
        if (ev.button !== 0) {
            return;
        }

        const initialX = ev.pageX;
        const initialWidth = this.root.el.offsetWidth;
        const resizeStoppingEvents = ["keydown", "pointerdown", "pointerup"];

        const removeListeners = () => {
            document.removeEventListener("pointermove", resizePanel, true);
            resizeStoppingEvents.forEach((stoppingEvent) => {
                document.removeEventListener(stoppingEvent, stopResize, true);
            });
            this._removeResizeListeners = null;
        };
        this._removeResizeListeners = removeListeners;

        const resizePanel = (ev) => {
            if (!this.root.el) {
                removeListeners();
                return;
            }
            ev.preventDefault();
            ev.stopPropagation();
            const maxWidth = Math.max(0.5 * window.innerWidth, initialWidth);
            const delta = ev.pageX - initialX;
            const newWidth = Math.min(maxWidth, Math.max(10, initialWidth + delta));
            this.width = `${newWidth}px`;
            this.root.el.style["min-width"] = this.width;
        };
        document.addEventListener("pointermove", resizePanel, true);

        const stopResize = (ev) => {
            if (ev.type === "pointerdown" && ev.button === 0) {
                return;
            }
            ev.preventDefault();
            ev.stopPropagation();

            removeListeners();
            const active = /** @type {HTMLElement} */ (document.activeElement);
            if (active && this.root.el?.contains(active)) {
                active.blur();
            }
        };
        resizeStoppingEvents.forEach((stoppingEvent) => {
            document.addEventListener(stoppingEvent, stopResize, true);
        });
    }
}
