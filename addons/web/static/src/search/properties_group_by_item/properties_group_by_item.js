// @ts-check
/** @odoo-module native */

import { Component, useChildSubEnv, useState } from "@odoo/owl";
import { ACCORDION, AccordionItem } from "@web/components/dropdown/accordion_item";
import { CheckboxItem } from "@web/components/dropdown/checkbox_item";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { useSearchModel } from "@web/search/search_model";
export class PropertiesGroupByItem extends Component {
    static template = "web.PropertiesGroupByItem";
    static components = { AccordionItem, CheckboxItem, DropdownItem };
    static props = {
        item: Object,
        onGroup: Function,
    };

    /** @type {{ definitionsLoaded: boolean }} */
    state;

    setup() {
        this.searchModel = useSearchModel();
        /** @type {{ definitionsLoaded: boolean }} */
        this.state = useState({ definitionsLoaded: false });
        useChildSubEnv({
            [ACCORDION]: {
                accordionStateChanged: (/** @type {boolean} */ isOpen) =>
                    isOpen ? this.loadDefinitions() : undefined,
            },
        });
    }

    /** @returns {Object[]} */
    get modelGroupByItems() {
        return this.searchModel.getSearchItems(
            (/** @type {any} */ searchItem) =>
                ["groupBy", "dateGroupBy"].includes(searchItem.type) &&
                searchItem.isProperty &&
                searchItem.propertyFieldName === this.props.item.fieldName,
        );
    }

    /** @returns {Object[]} */
    get groupByItems() {
        return this.state.definitionsLoaded ? this.modelGroupByItems : [];
    }

    /** @returns {boolean} */
    get isActive() {
        return this.modelGroupByItems.some((/** @type {any} */ item) => item.isActive);
    }

    /** @returns {boolean} */
    get isSingleParent() {
        const uniqueNames = new Set(
            this.groupByItems.map((/** @type {any} */ item) => item.definitionRecordId),
        );
        return uniqueNames.size < 2;
    }

    /** @returns {Promise<void>} */
    async loadDefinitions() {
        if (this.state.definitionsLoaded || this._loadingDefinitions) {
            return;
        }
        this._loadingDefinitions = true;
        try {
            await this.searchModel.updateSearchViewItemsProperty();
            this.state.definitionsLoaded = true;
        } finally {
            this._loadingDefinitions = false;
        }
    }

    /** @param {number[]} ids */
    onGroup(ids) {
        this.props.onGroup(ids);
    }
}
