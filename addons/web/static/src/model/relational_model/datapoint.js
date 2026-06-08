// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/datapoint - Abstract reactive base class for all data model nodes (records, lists, groups) */

import { markRaw } from "@odoo/owl";
import { SignalStore } from "@web/core/utils/reactive";

import { getId } from "./field_context.js";
/** @import { Field, FieldInfo } from "@web/model/types" */
/** @import { RelationalModel, RelationalModelConfig } from "./relational_model.js" */

export class DataPoint extends SignalStore {
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
        // Do NOT memoize on `this`: this datapoint is a reactive SignalStore, so
        // caching the result (writing `this._fieldNames`/`_fieldNamesSource`) during
        // this getter mutates reactive state *while rendering*. Any component that
        // reads `record.fieldNames` in its render (e.g. DomainField via getResModel)
        // would then re-render → recompute → re-write → infinite render loop. Reading
        // `activeFields` through the reactive proxy yields a fresh reference each call,
        // so the identity guard never holds anyway. Per reactive.js's `derived()`
        // contract, derived state is recomputed each access, not cached.
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
