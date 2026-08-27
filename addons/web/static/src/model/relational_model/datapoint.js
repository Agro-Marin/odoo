// @ts-check
/** @odoo-module native */

import { markRaw } from "@odoo/owl";
import { SignalStore } from "@web/core/utils/reactive";

import { getId } from "./field_context.js";
/** @import { Field, FieldInfo } from "@web/model/types" */
/** @import { RelationalModel, RelationalModelConfig } from "./relational_model.js" */

/**
 * @typedef {Record<string, unknown> | unknown[]} DataPointPayload
 */

export class DataPoint extends SignalStore {
    /**
     * @type {import("./record_edit_state.js").RecordEditState}
     */
    _editState;

    /** @type {Set<string>} */
    _loadedFieldNames;

    /**
     * @param {RelationalModel} model
     * @param {RelationalModelConfig} config
     * @param {DataPointPayload} data
     * @param {unknown} [options]
     */
    constructor(model, config, data, options) {
        super();
        this.id = getId("datapoint");
        this.model = model;
        markRaw(config.activeFields);
        markRaw(config.fields);
        /** @type {RelationalModelConfig} */
        this._config = config;
        this.setup(config, data, options);
    }

    /**
     * @abstract
     * @template [O={}]
     * @param {RelationalModelConfig} _config
     * @param {DataPointPayload} [_data]
     * @param {O} [_options]
     */
    setup(_config, _data, _options) {}

    get activeFields() {
        return this.config.activeFields;
    }

    get fields() {
        return this.config.fields;
    }

    get fieldNames() {
        return Object.keys(this.activeFields).filter(
            (fieldName) => !this.fields[fieldName].relatedPropertyField,
        );
    }

    get resModel() {
        return this.config.resModel;
    }

    get config() {
        return this._config;
    }

    get context() {
        return this.config.context;
    }
}
