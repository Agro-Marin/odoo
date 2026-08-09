// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/properties/property_definition */

import { Component, onWillUpdateProps, useEffect, useRef, useState } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { DomainSelector } from "@web/components/domain_selector/domain_selector";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { ModelSelector } from "@web/components/model_selector/model_selector";
import { Domain } from "@web/core/domain";
import { getSelectCreateDialog } from "@web/core/record_dialog_port";
import { _t } from "@web/core/translation";
import { KeepLast, SupersededError } from "@web/core/utils/concurrency";
import { uuid } from "@web/core/utils/format/strings";
import { useOwnedDialogs, useService } from "@web/core/utils/hooks";
import { Many2XAutocomplete } from "@web/fields/relational/many2x_autocomplete";

import { PropertyDefinitionSelection } from "./property_definition_selection.js";
import { PropertyTags } from "./property_tags.js";
import { PropertyValue } from "./property_value.js";

export class PropertyDefinition extends Component {
    static template = "web.PropertyDefinition";
    static components = {
        CheckBox,
        DomainSelector,
        Dropdown,
        DropdownItem,
        PropertyValue,
        Many2XAutocomplete,
        ModelSelector,
        PropertyDefinitionSelection,
        PropertyTags,
    };
    static props = {
        fieldName: { type: String },
        readonly: { type: Boolean, optional: true },
        canChangeDefinition: { type: Boolean, optional: true },
        propertyDefinition: { optional: true },
        context: { type: Object },
        isNewlyCreated: { type: Boolean, optional: true },
        propertyIndex: { type: Number },
        propertiesSize: { type: Number },
        onChange: { type: Function, optional: true },
        onDelete: { type: Function, optional: true },
        onPropertyMove: { type: Function, optional: true },
        close: { type: Function, optional: true },
        record: { type: Object, optional: true },
    };
    static _propertyParametersMap = new Map([
        ["comodel", ["many2one", "many2many"]],
        ["currency_field", ["monetary"]],
        ["domain", ["many2one", "many2many"]],
        ["selection", ["selection"]],
        ["tags", ["tags"]],
    ]);

    setup() {
        this.orm = useService("orm");

        this.keepLastCount = new KeepLast({ rejectSuperseded: true });
        this.keepLastModelDescription = new KeepLast({ rejectSuperseded: true });

        this.propertyDefinitionRef = useRef("propertyDefinition");
        this.addDialog = useOwnedDialogs();

        const defaultDefinition = {
            name: false,
            string: "",
            type: "char",
            default: "",
        };
        const propertyDefinition = {
            ...defaultDefinition,
            ...this.props.propertyDefinition,
        };

        this.state = useState({
            propertyDefinition: propertyDefinition,
            typeLabel: this._typeLabel(propertyDefinition.type),
            resModel: "",
            resModelDescription: "",
            matchingRecordsCount: undefined,
            propertyIndex: this.props.propertyIndex,
        });

        this._syncStateWithProps(propertyDefinition);

        this._domInputIdPrefix = uuid();

        onWillUpdateProps((newProps) => {
            this.state.propertyIndex = newProps.propertyIndex;
            return this._syncStateWithProps(newProps.propertyDefinition);
        });

        useEffect((event) => {
            if (this.labelFocused) {
                return;
            }
            this.labelFocused = true;
            const labelInput = /** @type {HTMLInputElement | undefined} */ (
                this.propertyDefinitionRef.el.querySelectorAll("input")[0]
            );
            if (labelInput) {
                if (this.props.isNewlyCreated) {
                    labelInput.select();
                } else {
                    labelInput.focus();
                }
            }
        });
    }

    /**
     * @returns {array}
     */
    get availablePropertyTypes() {
        return [
            ["char", _t("Text")],
            ["text", _t("Multiline Text")],
            ["html", _t("HTML")],
            ["boolean", _t("Checkbox")],
            ["integer", _t("Integer")],
            ["float", _t("Decimal")],
            ["monetary", _t("Monetary")],
            ["date", _t("Date")],
            ["datetime", _t("Date & Time")],
            ["selection", _t("Selection")],
            ["tags", _t("Tags")],
            ["many2one", _t("Many2one")],
            ["many2many", _t("Many2many")],
            ["separator", _t("Separator")],
        ];
    }

    get currencyFields() {
        return Object.values(this.props.record.fields).filter(
            (fieldDef) =>
                fieldDef.type === "many2one" && fieldDef.relation === "res.currency",
        );
    }

    get defaultCurrencyField() {
        const currencyFields = this.currencyFields.map((fieldDef) => fieldDef.name);
        return currencyFields.includes("currency_id")
            ? "currency_id"
            : currencyFields[0] || false;
    }

    get isFirst() {
        return this.state.propertyIndex === 0;
    }

    get isLast() {
        return this.state.propertyIndex === this.props.propertiesSize - 1;
    }

    /**
     * @returns {array}
     */
    get propertyTagValues() {
        return (this.state.propertyDefinition.tags || []).map((tag) => tag[0]);
    }

    /**
     * @returns {string}
     */
    getUniqueDomID(suffix) {
        return `property_definition_${this._domInputIdPrefix}_${suffix}`;
    }

    /**
     * @param {Event} event
     */
    onPropertyLabelChange(event) {
        const newString = /** @type {HTMLInputElement} */ (event.target).value;
        const propertyDefinition = {
            ...this.state.propertyDefinition,
            string: newString,
        };
        this.props.onChange(propertyDefinition);
        this.state.propertyDefinition = propertyDefinition;
    }

    /**
     * @param {KeyboardEvent} event
     */
    onPropertyLabelKeypress(event) {
        if (event.key !== "Enter") {
            return;
        }
        this.props.close();
    }

    /**
     * @param {object} newDefault
     */
    onDefaultChange(newDefault) {
        const propertyDefinition = {
            ...this.state.propertyDefinition,
            default: newDefault,
        };
        this.props.onChange(propertyDefinition);
        this.state.propertyDefinition = propertyDefinition;
    }

    /**
     * @param {string} newType
     */
    onPropertyTypeChange(newType) {
        const propertyDefinition = {
            ...this.state.propertyDefinition,
            type: newType,
        };
        if (["integer", "float", "monetary"].includes(newType)) {
            propertyDefinition.value = 0;
            propertyDefinition.default = 0;
        } else {
            propertyDefinition.value = false;
            propertyDefinition.default = false;
        }

        if (newType === "monetary") {
            propertyDefinition.currency_field = this.defaultCurrencyField;
        }

        if (newType === "separator") {
            propertyDefinition.fold_by_default = true;
        }

        PropertyDefinition._propertyParametersMap.forEach((types, param) => {
            if (!types.includes(propertyDefinition.type)) {
                delete propertyDefinition[param];
            }
        });

        this.props.onChange(propertyDefinition);
        this.state.propertyDefinition = propertyDefinition;
        if (!propertyDefinition.comodel) {
            this.state.resModel = "";
            this.state.resModelDescription = "";
        }
        this.state.typeLabel = this._typeLabel(newType);
    }

    /**
     * @param {string} newModel
     */
    async onModelChange(newModel) {
        const { label, technical } = /** @type {any} */ (newModel);

        const modelChanged = technical !== this.state.resModel;

        this.state.resModel = technical;
        this.state.resModelDescription = label;

        const propertyDefinition = {
            ...this.state.propertyDefinition,
            comodel: technical,
            default: modelChanged ? false : this.state.propertyDefinition.default,
            value: modelChanged ? false : this.state.propertyDefinition.value,
            domain: modelChanged ? false : this.state.propertyDefinition.domain,
        };
        this.props.onChange(propertyDefinition);
        this.state.propertyDefinition = propertyDefinition;
        await this._updateMatchingRecordsCount();
    }

    /**
     * @param {string} newDomain
     */
    async onDomainChange(newDomain) {
        const propertyDefinition = {
            ...this.state.propertyDefinition,
            domain: newDomain,
            default: false,
        };
        this.props.onChange(propertyDefinition);
        this.state.propertyDefinition = propertyDefinition;
        await this._updateMatchingRecordsCount();
    }

    onButtonDomainClick() {
        const SelectCreateDialog = getSelectCreateDialog();
        this.addDialog(SelectCreateDialog, {
            title: _t("Selected records"),
            noCreate: true,
            multiSelect: false,
            resModel: this.state.propertyDefinition.comodel,
            domain: new Domain(this.state.propertyDefinition.domain || "[]").toList(),
            context: this.props.context || {},
        });
    }

    /**
     * @param {string} direction
     */
    onPropertyMove(direction) {
        if (direction === "up") {
            this.state.propertyIndex--;
        } else {
            this.state.propertyIndex++;
        }
        this.props.onPropertyMove(direction);
    }

    /**
     * @param {array} newOptions
     */
    onSelectionOptionChange(newOptions) {
        const propertyDefinition = {
            ...this.state.propertyDefinition,
            selection: newOptions,
        };
        this.props.onChange(propertyDefinition);
        this.state.propertyDefinition = propertyDefinition;
    }

    /**
     * @param {Event & { target: HTMLInputElement }} ev
     */
    onSuffixChange(ev) {
        const propertyDefinition = {
            ...this.state.propertyDefinition,
            suffix: ev.target.value,
        };
        this.props.onChange(propertyDefinition);
        this.state.propertyDefinition = propertyDefinition;
    }

    /**
     * @param {array} newTags
     */
    onTagsChange(newTags) {
        const propertyDefinition = {
            ...this.state.propertyDefinition,
            tags: newTags,
        };
        this.props.onChange(propertyDefinition);
        this.state.propertyDefinition = propertyDefinition;
    }

    /**
     * @param {boolean} newValue
     */
    onViewInKanbanChange(newValue) {
        const propertyDefinition = {
            ...this.state.propertyDefinition,
            view_in_cards: newValue,
        };
        this.props.onChange(propertyDefinition);
        this.state.propertyDefinition = propertyDefinition;
    }

    /**
     * @param {boolean} checked
     */
    onFoldByDefaultChange(checked) {
        const propertyDefinition = {
            ...this.state.propertyDefinition,
            fold_by_default: checked,
        };
        this.props.onChange(propertyDefinition);
        this.state.propertyDefinition = propertyDefinition;
    }

    onCurrencyFieldUpdate(path) {
        const propertyDefinition = {
            ...this.state.propertyDefinition,
            currency_field: path,
        };
        this.props.onChange(propertyDefinition);
        this.state.propertyDefinition = propertyDefinition;
    }

    /**
     * @param {object} propertyDefinition
     */
    async _syncStateWithProps(propertyDefinition) {
        const newModel = propertyDefinition.comodel;
        const currentModel = this.state.resModel;

        this.state.propertyDefinition = propertyDefinition;
        this.state.typeLabel = this._typeLabel(propertyDefinition.type);
        this.state.resModel = newModel;

        if (newModel && newModel !== currentModel) {
            try {
                const result = await this.keepLastModelDescription.add(
                    this.orm.call("ir.model", "display_name_for", [[newModel]]),
                );
                if (!result || !result.length) {
                    return;
                }
                this.state.resModelDescription = result[0].display_name;
            } catch (error) {
                // Superseded is not an access failure. Falling through would
                // tell the user they lack access to a model they simply
                // stopped asking about.
                if (!(error instanceof SupersededError)) {
                    this.state.resModelDescription = _t(
                        'You do not have access to the model "%s".',
                        newModel,
                    );
                } else {
                    return;
                }
            }

            await this._updateMatchingRecordsCount();
        } else if (!newModel) {
            this.state.resModelDescription = "";
        }
    }

    async _updateMatchingRecordsCount() {
        if (this.state.resModel && this.state.resModel.length) {
            const domainList = new Domain(
                this.state.propertyDefinition.domain || "[]",
            ).toList();

            try {
                this.state.matchingRecordsCount = await this.keepLastCount.add(
                    this.orm.call(
                        this.state.propertyDefinition.comodel,
                        "search_count",
                        [domainList],
                    ),
                );
            } catch (error) {
                if (error instanceof SupersededError) {
                    return;
                }
                this.state.matchingRecordsCount = undefined;
            }
        } else {
            this.state.matchingRecordsCount = undefined;
        }
    }

    /**
     * @param {string} propertyType
     * @returns {string}
     */
    _typeLabel(propertyType) {
        const allTypes = this.availablePropertyTypes;
        return allTypes.find((type) => type[0] === propertyType)?.[1] ?? propertyType;
    }
}
