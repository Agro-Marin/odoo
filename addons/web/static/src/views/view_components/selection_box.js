// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";

export class SelectionBox extends Component {
    static components = {};
    static template = "web.SelectionBox";
    static props = {
        root: { type: Object },
    };
    /**
     * @returns {import("@web/model/relational_model/dynamic_record_list").DynamicRecordList
     * & import("@web/model/relational_model/dynamic_group_list").DynamicGroupList}
     */
    get root() {
        return this.props.root;
    }
    /** @returns {number} */
    get nbSelected() {
        return this.selectedRecords.length;
    }
    /** @returns {number} */
    get nbTotal() {
        return /** @type {number} */ (
            this.root.isGrouped ? this.root.recordCount : this.root.count
        );
    }
    /** @returns {boolean} */
    get hasLimitedCount() {
        return /** @type {boolean} */ (this.root.hasLimitedCount);
    }
    /** @returns {boolean} */
    get isDomainSelected() {
        return this.root.isDomainSelected;
    }
    /** @returns {boolean} */
    get isPageSelected() {
        return (
            this.nbSelected === this.root.records.length &&
            (!this.isRecordCountTrustable || this.nbTotal > this.selectedRecords.length)
        );
    }
    /** @returns {boolean} */
    get isRecordCountTrustable() {
        return this.root.isRecordCountTrustable;
    }
    /** @returns {import("@web/model/relational_model/record").RelationalRecord[]} */
    get selectedRecords() {
        return this.root.selection;
    }
    onUnselectAll() {
        this.selectedRecords.forEach((record) => {
            record.toggleSelection(false);
        });
        this.root.selectDomain(false);
    }
    onSelectDomain() {
        this.root.selectDomain(true);
    }
}
