// @ts-check
/** @odoo-module native */

import { Component, onWillRender } from "@odoo/owl";
import { useRenderCounter } from "@web/core/utils/render_instrumentation";

/**
 * @typedef {import("./list_renderer").ListRowApi} ListRowApi
 * @typedef {import("./list_renderer").ListRowFlags} ListRowFlags
 */

const listRecordRowProps = {
    record: { type: Object },
    group: { type: [Object, { value: null }, { value: false }], optional: true },
    groupId: { type: [String, Number, { value: false }], optional: true },

    api: { type: Object },
    flags: { type: Object },

    list: { type: Object },
    archInfo: { type: Object },
    columns: { type: Array },
    activeActions: { type: Object, optional: true },
    recordRowTemplate: { type: String, optional: true },
    onOpenFormView: { type: Function, optional: true },

    readonly: { type: Boolean, optional: true },
    isEdited: { type: Boolean },
    canResequence: { type: Boolean },
    hasSelectors: { type: Boolean },
    hasOpenFormViewColumn: { type: Boolean },
    displayOptionalFields: { type: Boolean },
    isX2Many: { type: Boolean },
    rowIndex: { type: Number, optional: true },

    "*": true,
};

export class ListRecordRow extends Component {
    static template = "web.ListRecordRow";
    static components = {};
    static props = listRecordRowProps;

    setup() {
        useRenderCounter("list.ListRecordRow");
        onWillRender(() => {
            this.props.api.markRowRender(String(this.props.record.id));
        });
    }

    get record() {
        return this.props.record;
    }

    get group() {
        return this.props.group;
    }

    get groupId() {
        return this.props.groupId;
    }

    /** @returns {ListRowApi} */
    get api() {
        return this.props.api;
    }

    /** @returns {ListRowFlags} */
    get flags() {
        return this.props.flags;
    }

    get _canSelectRecord() {
        return this.props.flags.canSelectRecord;
    }

    get editedRecord() {
        return this.props.flags.isEditing ? this.props.api.getEditedRecord() : null;
    }

    get gridState() {
        return this.props.api.getGridState();
    }

    get _displaySaveNotification() {
        return this.props.api.displaySaveNotification;
    }

    get hasSelectors() {
        return this.props.hasSelectors;
    }

    get hasOpenFormViewColumn() {
        return this.props.hasOpenFormViewColumn;
    }

    get displayOptionalFields() {
        return this.props.displayOptionalFields;
    }

    get isX2Many() {
        return this.props.isX2Many;
    }

    get activeActions() {
        return this.props.activeActions;
    }

    /** @param {any} record */
    getRowClass(record) {
        return this.props.api.getRowClass(record);
    }

    /** @param {any} record */
    getColumns(record) {
        return this.props.api.getColumns(record);
    }

    /**
     * @param {string} invisible
     * @param {any} record
     */
    evalInvisible(invisible, record) {
        return this.props.api.evalInvisible(invisible, record);
    }

    /**
     * @param {any} column
     * @param {any} record
     */
    canUseFormatter(column, record) {
        return this.props.api.canUseFormatter(column, record);
    }

    /**
     * @param {any} column
     * @param {any} record
     */
    getFormattedValue(column, record) {
        return this.props.api.getFormattedValue(column, record);
    }

    /**
     * @param {any} column
     * @param {any} record
     */
    getCellClass(column, record) {
        return this.props.api.getCellClass(column, record);
    }

    /**
     * @param {any} column
     * @param {any} record
     * @param {string} [formattedValue]
     */
    getCellTitle(column, record, formattedValue) {
        return this.props.api.getCellTitle(column, record, formattedValue);
    }

    /** @param {any} column */
    getFieldClass(column) {
        return this.props.api.getFieldClass(column);
    }

    /**
     * @param {any} record
     * @param {any} column
     */
    getFieldProps(record, column) {
        return this.props.api.getFieldProps(record, column);
    }

    /** @param {any} record */
    displayDeleteIcon(record) {
        return this.props.api.displayDeleteIcon(record);
    }

    /**
     * @param {any} record
     * @param {any} column
     * @param {PointerEvent} ev
     * @param {boolean} [newWindow]
     */
    onCellClicked(record, column, ev, newWindow) {
        return this.props.api.onCellClicked(record, column, ev, newWindow);
    }

    /**
     * @param {any} record
     * @param {any} column
     * @param {PointerEvent} ev
     */
    onButtonCellClicked(record, column, ev) {
        return this.props.api.onButtonCellClicked(record, column, ev);
    }

    /**
     * @param {any} record
     * @param {PointerEvent} ev
     */
    onRemoveCellClicked(record, ev) {
        return this.props.api.onRemoveCellClicked(record, ev);
    }

    /**
     * @param {KeyboardEvent} ev
     * @param {any} [group]
     * @param {any} [record]
     */
    onCellKeydown(ev, group = null, record = null) {
        return this.props.api.onCellKeydown(ev, group, record);
    }

    /**
     * @param {any} record
     */
    toggleRecordSelection(record) {
        return this.props.api.toggleRecordSelection(record);
    }

    /**
     * @param {any} record
     * @param {TouchEvent} ev
     */
    onRowTouchStart(record, ev) {
        return this.props.api.onRowTouchStart(record, ev);
    }

    /** @param {any} record */
    onRowTouchEnd(record) {
        return this.props.api.onRowTouchEnd(record);
    }

    /** @param {any} record */
    onRowTouchMove(record) {
        return this.props.api.onRowTouchMove(record);
    }

    /**
     * @param {any} record
     * @param {PointerEvent} ev
     */
    onClickCapture(record, ev) {
        return this.props.api.onClickCapture(record, ev);
    }

    /** @param {MouseEvent} ev */
    ignoreEventInSelectionMode(ev) {
        return this.props.api.ignoreEventInSelectionMode(ev);
    }
}

/** @type {WeakMap<any, any>} */
const rowClassRegistry = new WeakMap();

/**
 * @param {any} RendererClass
 * @returns {typeof ListRecordRow}
 */
export function getRowComponentClass(RendererClass) {
    let RowClass = rowClassRegistry.get(RendererClass);
    if (!RowClass) {
        RowClass = class extends ListRecordRow {};
        Object.defineProperty(RowClass, "name", {
            value: `ListRecordRow_${RendererClass.name}`,
            configurable: true,
        });
        Object.defineProperty(RowClass, "components", {
            configurable: true,
            get() {
                return RendererClass.components;
            },
            set(value) {
                Object.defineProperty(this, "components", {
                    value,
                    writable: true,
                    configurable: true,
                    enumerable: true,
                });
            },
        });
        rowClassRegistry.set(RendererClass, RowClass);
    }
    return RowClass;
}
