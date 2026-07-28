// @ts-check
/** @odoo-module native */

/** @module @web/search/properties_group_by_item/properties_group_by_item - Group-by dropdown item that lazily loads property definitions for grouping */

import { Component, useChildSubEnv, useState } from "@odoo/owl";
import { ACCORDION, AccordionItem } from "@web/components/dropdown/accordion_item";
import { CheckboxItem } from "@web/components/dropdown/checkbox_item";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
/**
 * Group-by dropdown item for model properties fields.
 * Lazily loads property definitions on first open, then displays
 * sub-items for each property that supports grouping.
 */
export class PropertiesGroupByItem extends Component {
    static template = "web.PropertiesGroupByItem";
    static components = { AccordionItem, CheckboxItem, DropdownItem };
    static props = {
        item: Object,
        onGroup: Function,
    };

    setup() {
        /** @type {{ definitionsLoaded: boolean }} */
        this.state = useState({ definitionsLoaded: false });
        useChildSubEnv({
            [ACCORDION]: {
                accordionStateChanged: () => this.loadDefinitions(),
            },
        });
    }

    /**
     * Read live from the search model rather than from a snapshot taken when
     * the accordion opened: the activation shown here also changes from the
     * outside (a facet removed, a favorite applied, the query cleared), and a
     * cached copy kept those items rendering as selected forever.
     * @returns {Object[]}
     */
    get groupByItems() {
        if (!this.state.definitionsLoaded) {
            return [];
        }
        return this.env.searchModel.getSearchItems(
            (searchItem) =>
                ["groupBy", "dateGroupBy"].includes(searchItem.type) &&
                searchItem.isProperty &&
                searchItem.propertyFieldName === this.props.item.fieldName,
        );
    }

    /**
     * The properties field is considered as active if one of its property is active.
     * @returns {boolean}
     */
    get isActive() {
        return this.groupByItems.some((item) => item.isActive);
    }

    /**
     * True if all group items come from the same definition record.
     * @returns {boolean}
     */
    get isSingleParent() {
        const uniqueNames = new Set(
            this.groupByItems.map((item) => item.definitionRecordId),
        );
        return uniqueNames.size < 2;
    }

    /**
     * Dynamically load the definition, only when needed (if we open the dropdown).
     * @returns {Promise<void>}
     */
    async loadDefinitions() {
        if (this.state.definitionsLoaded || this._loadingDefinitions) {
            return;
        }
        this._loadingDefinitions = true;
        try {
            await this.env.searchModel.fillSearchViewItemsProperty();
            this.state.definitionsLoaded = true;
        } finally {
            this._loadingDefinitions = false;
        }
    }

    /**
     * Callback to group records per one property.
     * @param {number[]} ids - Search item IDs to activate for grouping.
     */
    onGroup(ids) {
        this.props.onGroup(ids);
    }
}
