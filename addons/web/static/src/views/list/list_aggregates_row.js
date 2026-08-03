// @ts-check
/** @odoo-module native */

/** @module views/list/list_aggregates_row */

import { Component, onWillRender, useRef } from "@odoo/owl";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { useAutofocus } from "@web/core/utils/hooks";

import { useListAggregates } from "./list_aggregates.js";
import {
    getAggregateColumns as getAggregateColumnsUtil,
    getGroupNameCellColSpan as getGroupNameCellColSpanUtil,
} from "./list_group_layout.js";

/**
 * @extends Component
 */
export class ListAggregatesRow extends Component {
    static template = "web.ListAggregatesRow";

    static props = {
        /** @type {any} */
        list: Object,
        /** @type {any} */
        archInfo: Object,
        /**
         * @type {any}
         */
        columns: Array,
        /** @type {any} */
        optionalActiveFields: Object,
        hasSelectors: Boolean,
        hasOpenFormViewColumn: Boolean,
        displayOptionalFields: Boolean,
        hasActionsColumn: Boolean,
        activeActions: Object,
        canCreateGroup: Boolean,
        showGroupInput: Boolean,
        onShowGroupInput: Function,
        onHideGroupInput: Function,
        /**
         * @type {(value: string) => void}
         */
        onGroupInputConfirm: Function,
    };

    /** @type {number} */
    _renderId;
    /** @type {{ renderId: number, value: any }} */
    _aggregatesCache;
    /** @type {ReturnType<typeof useListAggregates>} */
    agg;
    /** @type {import("@odoo/owl").Ref} */
    groupInputRef;

    setup() {
        this.groupInputRef = useRef("groupInput");
        useAutofocus({ refName: "groupInput" });

        // This row is not a full ListRenderer, so it passes the aggregates hook a
        // partial grid context -- exactly the four getters the hook reads.
        this.agg = useListAggregates({
            getColumns: () => this.columns,
            getFields: () => this.props.list.fields,
            getProps: () => this.props,
            getOptionalActiveFields: () => this.props.optionalActiveFields,
        });

        this._renderId = 0;
        this._aggregatesCache = { renderId: -1, value: null };
        onWillRender(() => {
            this._renderId++;
        });
    }

    /** @returns {any[]} */
    get columns() {
        return this.props.columns;
    }

    /** @returns {Record<string, object>} */
    get aggregates() {
        if (this._aggregatesCache.renderId !== this._renderId) {
            this._aggregatesCache = {
                renderId: this._renderId,
                value: this.agg.computeAggregates(),
            };
        }
        return this._aggregatesCache.value;
    }

    /** @returns {Record<string, any>} */
    get fields() {
        return this.props.list.fields;
    }

    /** @returns {any[]} */
    getAggregateColumns() {
        return getAggregateColumnsUtil(
            /** @type {any} */ (this.columns),
            this.fields,
            this.aggregates,
        );
    }

    /** @returns {number} */
    getGroupNameCellColSpan() {
        return getGroupNameCellColSpanUtil(
            /** @type {any} */ (this.columns),
            this.fields,
            this.aggregates,
            { hasSelectors: this.props.hasSelectors },
        );
    }

    /**
     * @param {KeyboardEvent} ev
     */
    onGroupInputKeydown(ev) {
        const hotkey = getActiveHotkey(ev);
        if (hotkey === "enter") {
            ev.stopPropagation();
            this._confirmGroupInput();
        }
        if (hotkey === "escape") {
            ev.stopPropagation();
            this.props.onHideGroupInput();
        }
    }

    _confirmGroupInput() {
        const value = /** @type {HTMLInputElement} */ (this.groupInputRef.el).value;
        this.props.onGroupInputConfirm(value);
    }

    /**
     * @param {MouseEvent} ev
     * @param {any} value
     * @param {string} fieldName
     */
    openMultiCurrencyPopover(ev, value, fieldName) {
        this.agg.openMultiCurrencyPopover(ev, value, fieldName);
    }
}
