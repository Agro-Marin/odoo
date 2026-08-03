// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/reference/reference_field */

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { KeepLast } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
import { useRecordObserver } from "@web/fields/hooks/record_observer";
import { computeM2OProps, Many2One } from "@web/fields/relational/many2one/many2one";
import {
    extractM2OFieldProps,
    m2oSupportedOptions,
    Many2OneField,
} from "@web/fields/relational/many2one/many2one_field";

/**
 * @typedef ReferenceValue
 * @property {string} resModel
 * @property {number} resId
 * @property {string} displayName
 */

export class ReferenceField extends Component {
    static template = "web.ReferenceField";
    static components = { Many2One };
    static props = {
        ...Many2OneField.props,
        hideModel: { type: Boolean, optional: true },
        modelField: { type: String, optional: true },
    };

    setup() {
        /** @type {{formattedCharValue?: ReferenceValue, modelName?: string}} */
        this.state = useState({
            formattedCharValue: undefined,
            modelName: undefined,
            currentRelation: undefined,
        });
        this.nameService = useService("name");
        const keepLast = new KeepLast();
        if (this._isCharField(this.props)) {
            let currentValue = undefined;
            useRecordObserver(async (record, props) => {
                if (currentValue !== record.data[props.name]) {
                    /** @type {any} */ (this.state).formattedCharValue =
                        await keepLast.add(this._fetchReferenceCharData(props));
                    currentValue = record.data[props.name];
                }
            });
        } else if (this.props.modelField) {
            useRecordObserver(async (record, props) => {
                if (this.currentModelId !== record.data[props.modelField]?.id) {
                    /** @type {any} */ (this.state).modelName = await keepLast.add(
                        this._fetchModelTechnicalName(props),
                    );
                    if (this.currentModelId !== undefined) {
                        record.update({ [props.name]: false });
                    }
                    this.currentModelId = record.data[props.modelField]?.id;
                }
            });
        }
    }

    /** @returns {Object} */
    get m2oProps() {
        const value = this.getValue();
        return {
            ...computeM2OProps(this.props),
            relation: this.getRelation(),
            value: value && {
                id: value.resId,
                display_name: value.displayName,
            },
            update: this.updateM2O.bind(this),
        };
    }
    /** @returns {Array<[string, string]>} */
    get selection() {
        if (!this._isCharField(this.props) && !this.hideModelSelector) {
            return this.props.record.fields[this.props.name].selection;
        }
        return [];
    }

    /** @returns {boolean|string} */
    get hideModelSelector() {
        return this.props.hideModel || this.props.modelField;
    }

    /** @returns {string|undefined} */
    getRelation() {
        const modelName = this.getModelName();
        if (modelName) {
            return modelName;
        }

        const value = /** @type {any} */ (this.getValue());
        if (value?.resModel) {
            return value.resModel;
        } else {
            return /** @type {any} */ (this.state).currentRelation;
        }
    }

    /**
     * @returns {ReferenceValue|false}
     */
    getValue() {
        if (this._isCharField(this.props)) {
            return this.state.formattedCharValue;
        } else {
            return this.props.record.data[this.props.name];
        }
    }

    /**
     * @returns {string|undefined}
     */
    getModelName() {
        return this.hideModelSelector && this.state.modelName;
    }

    /** @param {string} value */
    updateModel(value) {
        /** @type {any} */ (this.state).currentRelation = value;
        this.props.record.update({ [this.props.name]: false });
    }

    /** @param {{ id: number, display_name: string }|false} value */
    updateM2O(value) {
        const resModel = this.getRelation();
        if (this._isCharField(this.props)) {
            this.props.record.update({
                [this.props.name]: value ? `${resModel},${value.id}` : false,
            });
            return;
        }
        this.props.record.update({
            [this.props.name]: value && {
                resModel,
                resId: value.id,
                displayName: value.display_name,
            },
        });
    }

    _isCharField(props) {
        return props.record.fields[props.name].type === "char";
    }

    /**
     * @returns {Promise<{ resId: number, resModel: string, displayName: string }|false>}
     */
    async _fetchReferenceCharData(props) {
        const recordData = props.record.data[props.name];
        if (!recordData) {
            return false;
        }
        const [resModel, _resId] = recordData.split(",");
        const resId = Number.parseInt(_resId, 10);
        if (!resModel || !resId) {
            return false;
        }
        // The name service batches every reference on the page into one read,
        // and drops its cache when the action changes -- a bespoke cache here
        // held a renamed record's old name for the whole session.
        const displayNames = await this.nameService.loadDisplayNames(resModel, [resId]);
        const displayName = displayNames[resId];
        if (typeof displayName !== "string") {
            return false;
        }
        return { resId, resModel, displayName };
    }

    _assertMany2OneToIrModel(props) {
        const field = props.modelField && props.record.fields[props.modelField];
        if (field && (field.type !== "many2one" || field.relation !== "ir.model")) {
            throw new Error(
                `The model_field (${props.modelField}) of the reference field ${props.name} must be a many2one('ir.model').`,
            );
        }
    }

    /**
     * @returns {Promise<string|false>}
     */
    async _fetchModelTechnicalName(props) {
        this._assertMany2OneToIrModel(props);
        const record = props.record;
        const modelId = record.data[props.modelField]?.id;
        if (!modelId) {
            return false;
        }
        const { specialDataCaches, orm } = props.record.model;
        const key = `__reference__ir_model-${modelId}`;
        if (!specialDataCaches.has(key)) {
            specialDataCaches.set(
                key,
                orm.read("ir.model", [modelId], ["model"]).catch((e) => {
                    specialDataCaches.delete(key);
                    throw e;
                }),
            );
        }
        const result = await specialDataCaches.get(key);
        return result[0]?.model ?? false;
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const referenceField = {
    component: ReferenceField,
    displayName: _t("Reference"),
    // extractM2OFieldProps is what builds the props, so every many2one option
    // is honoured here too and belongs in the declaration.
    supportedOptions: [
        ...m2oSupportedOptions,
        {
            label: _t("Hide model"),
            name: "hide_model",
            type: "boolean",
        },
        {
            label: _t("Model field"),
            name: "model_field",
            type: "field",
            availableTypes: ["many2one"],
        },
    ],
    supportedTypes: ["reference", "char"],
    fieldDependencies: ({ options }) =>
        options.model_field
            ? [{ name: options.model_field, optional: true, readonly: true }]
            : [],
    extractProps(staticInfo, dynamicInfo) {
        const { options } = staticInfo;
        const props = extractM2OFieldProps(staticInfo, dynamicInfo);
        props.hideModel = !!options.hide_model;
        props.modelField = options.model_field;
        return props;
    },
};

registerField("reference", referenceField);
