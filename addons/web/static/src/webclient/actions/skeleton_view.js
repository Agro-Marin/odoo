// @ts-check
/** @odoo-module native */

import { Component, onMounted } from "@odoo/owl";

/** @param {number} length */
const indices = (length) => Object.freeze(Array.from({ length }, (_, i) => i));

const LIST_ROWS = indices(8);
const LIST_COLS = indices(5);
const KANBAN_CARDS = indices(3);
const KANBAN_GROUPS = indices(3);
const FORM_FIELDS = indices(6);

export class SkeletonView extends Component {
    static template = "web.SkeletonView";
    static props = {
        onMounted: Function,
        viewType: { type: String, optional: true },
        withControlPanel: { type: Boolean, optional: true },
        "*": true,
    };

    listRows = LIST_ROWS;
    listCols = LIST_COLS;
    kanbanCards = KANBAN_CARDS;
    kanbanGroups = KANBAN_GROUPS;
    formFields = FORM_FIELDS;

    setup() {
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
