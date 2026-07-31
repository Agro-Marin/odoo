// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/skeleton_view */

import { Component, onMounted } from "@odoo/owl";

export class SkeletonView extends Component {
    static template = "web.SkeletonView";
    static props = {
        onMounted: Function,
        viewType: { type: String, optional: true },
        withControlPanel: { type: Boolean, optional: true },
        "*": true,
    };

    setup() {
        /** @type {number[]} */
        this.listRows = Array.from({ length: 8 }, (_, i) => i);
        /** @type {number[]} */
        this.listCols = Array.from({ length: 5 }, (_, i) => i);
        /** @type {number[]} */
        this.kanbanCards = Array.from({ length: 3 }, (_, i) => i);
        /** @type {number[]} */
        this.kanbanGroups = Array.from({ length: 3 }, (_, i) => i);
        /** @type {number[]} */
        this.formFields = Array.from({ length: 6 }, (_, i) => i);
        onMounted(() => this.props.onMounted());
    }

    /** @returns {string} */
    get viewType() {
        return this.props.viewType || "generic";
    }

    /**
     * @param {number} row
     * @param {number} col
     * @returns {number}
     */
    cellWidth(row, col) {
        return 35 + ((row * 7 + col * 13) % 45);
    }
}
