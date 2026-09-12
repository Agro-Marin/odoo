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
