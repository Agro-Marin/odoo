// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/datapoint - Abstract reactive base class for all data model nodes (records, lists, groups) */

import { markRaw } from "@odoo/owl";
import { Reactive } from "@web/core/utils/reactive";

import { getId } from "./field_context.js";
/** @import { Field, FieldInfo } from "@web/model/types" */
/** @import { RelationalModel, RelationalModelConfig } from "./relational_model.js" */

export class DataPoint extends Reactive {
    /**
     * @param {RelationalModel} model
     * @param {RelationalModelConfig} config
     * @param {Record<string, unknown>} data
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
     * @param {Record<string, unknown>} [_data]
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
        const af = this.activeFields;
        if (!this._fieldNames || this._fieldNamesSource !== af) {
            this._fieldNamesSource = af;
            this._fieldNames = Object.keys(af).filter(
                (fieldName) => !this.fields[fieldName].relatedPropertyField,
            );
        }
        return this._fieldNames;
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
