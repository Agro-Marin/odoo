// @ts-check
/** @odoo-module native */

/** @module @web/search/search_bar_menu/search_bar_menu - Dropdown menu grouping Filter, Group By, Favorites, and search panels */

import { Component, useState } from "@odoo/owl";
import { AccordionItem } from "@web/components/dropdown/accordion_item";
import { CheckboxItem } from "@web/components/dropdown/checkbox_item";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { SearchModelEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { sortBy } from "@web/core/utils/collections/arrays";
import { useBus, useService } from "@web/core/utils/hooks";
import { CustomGroupByItem } from "@web/search/custom_group_by_item/custom_group_by_item";
import { PropertiesGroupByItem } from "@web/search/properties_group_by_item/properties_group_by_item";
import {
    editFavoriteFilter,
    FACET_ICONS,
    GROUPABLE_TYPES,
} from "@web/search/utils/misc";

const favoriteMenuRegistry = registry.category("favoriteMenu");

// Favorite-menu items are mounted under the search-bar's Favorites dropdown.
// `groupNumber` clusters items visually; `isDisplayed` filters by env/config.
favoriteMenuRegistry.addValidation({
    Component: Function,
    groupNumber: { type: Number, optional: true },
    isDisplayed: { type: Function, optional: true },
    "*": true,
});

/**
 * Dropdown menu, rendered in the search bar, that groups the Filter,
 * Group By (incl. custom/property group-bys), and Favorites panels, plus
 * registry-provided favorite menu items.
 */
export class SearchBarMenu extends Component {
    static template = "web.SearchBarMenu";
    static components = {
        Dropdown,
        DropdownItem,
        CheckboxItem,
        CustomGroupByItem,
        AccordionItem,
        PropertiesGroupByItem,
    };
    static props = {
        slots: {
            type: Object,
            optional: true,
            shape: {
                default: { optional: true },
            },
        },
        dropdownState: { ...Dropdown.props.state },
    };

    setup() {
        this.facet_icons = FACET_ICONS;
        // Filter
        this.actionService = useService("action");
        // Favorite
        this.state = useState({ sharedFavoritesExpanded: false });
        useBus(
            this.env.searchModel,
            SearchModelEvent.UPDATE,
            /** @type {any} */ (this.render),
        );
    }

    // GroupBy
    /**
     * Groupable fields, sorted by label. A live getter rather than a setup-time
     * snapshot: `fillSearchViewItemsProperty` (properties flow) mutates
     * `searchViewFields` at runtime, so a snapshot could go stale — matching the
     * live-view convention `SearchBar.searchItemsFields` documents. Recomputing
     * a sortBy over ~50 fields per menu render is negligible.
     * @returns {Object[]}
     */
    get fields() {
        const fields = [];
        for (const [fieldName, field] of Object.entries(
            this.env.searchModel.searchViewFields,
        )) {
            if (this.validateField(fieldName, field)) {
                fields.push(Object.assign({ name: fieldName }, field));
            }
        }
        return sortBy(fields, "string");
    }

    // Filter Panel
    /** @returns {Object[]} enriched filter and dateFilter search items */
    get filterItems() {
        return this.env.searchModel.getSearchItems((searchItem) =>
            ["filter", "dateFilter"].includes(searchItem.type),
        );
    }

    async onAddCustomFilterClick() {
        this.env.searchModel.spawnCustomFilterDialog();
    }

    /**
     * @param {Object} param0
     * @param {number} param0.itemId
     * @param {number} [param0.optionId]
     */
    onFilterSelected({ itemId, optionId }) {
        if (optionId) {
            this.env.searchModel.toggleDateFilter(itemId, optionId);
        } else {
            this.env.searchModel.toggleSearchItem(itemId);
        }
    }

    // GroupBy Panel
    /**
     * @returns {boolean}
     */
    get hideCustomGroupBy() {
        return this.env.searchModel.hideCustomGroupBy || false;
    }

    /**
     * @returns {Object[]}
     */
    get groupByItems() {
        return this.env.searchModel.getSearchItems(
            (searchItem) =>
                ["groupBy", "dateGroupBy"].includes(searchItem.type) &&
                !searchItem.isProperty,
        );
    }

    /**
     * @param {string} fieldName
     * @param {Object} field
     * @returns {boolean}
     */
    validateField(fieldName, field) {
        const { groupable, type } = field;
        return groupable && fieldName !== "id" && GROUPABLE_TYPES.includes(type);
    }

    /**
     * @param {Object} param0
     * @param {number} param0.itemId
     * @param {number} [param0.optionId]
     */
    onGroupBySelected({ itemId, optionId }) {
        if (optionId) {
            this.env.searchModel.toggleDateGroupBy(itemId, optionId);
        } else {
            this.env.searchModel.toggleSearchItem(itemId);
        }
    }

    /**
     * @param {string} fieldName
     */
    onAddCustomGroup(fieldName) {
        this.env.searchModel.createNewGroupBy(fieldName);
    }

    // Favorite Panel

    /** @returns {Object[]} private favorite search items (owned by current user) */
    get favorites() {
        return this.env.searchModel.getSearchItems(
            (searchItem) =>
                searchItem.type === "favorite" && searchItem.userIds.length === 1,
        );
    }

    /** @returns {Object[]} all shared favorite search items */
    get allSharedFavorites() {
        return this.env.searchModel.getSearchItems(
            (searchItem) =>
                searchItem.type === "favorite" && searchItem.userIds.length !== 1,
        );
    }

    /** @returns {Object[]} shared favorite search items (collapsed to 3 until expanded) */
    get sharedFavorites() {
        const sharedFavorites = this.allSharedFavorites;
        const expanded =
            this.state.sharedFavoritesExpanded || sharedFavorites.length <= 4;
        return expanded ? sharedFavorites : sharedFavorites.slice(0, 3);
    }

    /** @returns {{ Component: Function, groupNumber: number, key: string }[]} registry-provided favorite menu items */
    get otherItems() {
        const registryMenus = [];
        for (const item of favoriteMenuRegistry.getAll()) {
            if (
                "isDisplayed" in item
                    ? item.isDisplayed(
                          /** @type {import("@web/env").OdooEnv} */ (this.env),
                      )
                    : true
            ) {
                registryMenus.push({
                    Component: item.Component,
                    groupNumber: item.groupNumber,
                    key: item.Component.name,
                });
            }
        }
        return registryMenus;
    }

    /** @param {number} itemId */
    onFavoriteSelected(itemId) {
        this.env.searchModel.toggleSearchItem(itemId);
    }

    /** @param {number} itemId */
    editFavorite(itemId) {
        editFavoriteFilter(
            this.actionService,
            this.env.searchModel.searchItems[itemId].serverSideId,
        );
    }
}
