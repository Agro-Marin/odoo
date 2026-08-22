// @ts-check
/** @odoo-module native */

import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import {
    placeholderFieldOption,
    relationalPermissionAttributes,
} from "@web/fields/field_options";
import { standardFieldProps } from "@web/fields/standard_field_props";

import { computeM2OProps, Many2One } from "./many2one.js";

/** @type {import("registries").FieldsRegistryItemShape["supportedOptions"]} */
export const m2oSupportedOptions = [
    {
        label: _t("Disable opening"),
        name: "no_open",
        type: "boolean",
    },
    {
        label: _t("Disable creation"),
        name: "no_create",
        type: "boolean",
        help: _t(
            "If checked, users won't be able to create records through the autocomplete dropdown at all.",
        ),
    },
    {
        label: _t("Disable 'Create' option"),
        name: "no_quick_create",
        type: "boolean",
        help: _t(
            "If checked, users will not be able to create records based on the text input; they will still be able to create records via a popup form.",
        ),
    },
    {
        label: _t("Disable 'Create and Edit' option"),
        name: "no_create_edit",
        type: "boolean",
        help: _t(
            "If checked, users will not be able to create records based through a popup form; they will still be able to create records based on the text input.",
        ),
    },
    {
        label: _t("Typeahead search"),
        name: "search_threshold",
        type: "number",
        help: _t(
            "Defines the minimum number of characters to perform the search. If not set, the search is performed on focus.",
        ),
    },
    placeholderFieldOption(),
    {
        label: _t("Quick-create field"),
        name: "create_name_field",
        type: "string",
        help: _t(
            "Field filled in with the typed text when creating a record from the dropdown. Defaults to 'name'.",
        ),
    },
    {
        label: _t("Scan barcode"),
        name: "can_scan_barcode",
        type: "boolean",
        help: _t("Offer a barcode scanner button on mobile devices."),
    },
    {
        label: _t("Search memoization"),
        name: "search_memoization",
        type: "selection",
        default: "exact",
        choices: [
            { label: _t("Repeat every search"), value: "none" },
            { label: _t("Skip a search already known to be empty"), value: "exact" },
            {
                label: _t("Skip any search extending an empty one"),
                value: "substring",
            },
        ],
        help: _t(
            "'substring' assumes name_search is a plain ilike, so a longer term " +
                "cannot match where a shorter one did not. Models that also match on " +
                "another field (a barcode, a reference) must not use it.",
        ),
    },
];
/**
 * @type {import("registries").FieldsRegistryItemShape["supportedAttributes"]}
 */
export const m2oSupportedAttributes = relationalPermissionAttributes();

/** @type {import("registries").FieldsRegistryItemShape["supportedTypes"]} */
const m2oSupportedTypes = ["many2one"];

/**
 * @param {import("@odoo/owl").ComponentConstructor} component
 * @returns {import("registries").FieldsRegistryItemShape}
 */
export function buildM2OFieldDescription(component) {
    return {
        component,
        displayName: _t("Many2one"),
        extractProps: extractM2OFieldProps,
        supportedOptions: m2oSupportedOptions,
        supportedAttributes: m2oSupportedAttributes,
        supportedTypes: m2oSupportedTypes,
    };
}

/**
 * @param {Record<string, any>} staticInfo
 * @returns {{ canCreate: boolean, canCreateEdit: boolean, canQuickCreate: boolean }}
 */
export function extractCreatePermissions({ attrs, options }) {
    const hasCreatePermission = attrs.can_create
        ? evaluateBooleanExpr(attrs.can_create)
        : true;
    const canCreate = options.no_create ? false : hasCreatePermission;
    return {
        canCreate,
        canCreateEdit: canCreate && !options.no_create_edit,
        canQuickCreate: canCreate && !options.no_quick_create,
    };
}

/**
 * @param {{ attrs: Record<string, any> }} staticInfo
 * @returns {boolean}
 */
export function extractWritePermission({ attrs }) {
    return attrs.can_write ? evaluateBooleanExpr(attrs.can_write) : true;
}

/**
 * @param {{ attrs: Record<string, any>, options: Record<string, any> } & Record<string, any>} staticInfo
 * @param {Record<string, any>} dynamicInfo
 * @returns {Record<string, any>}
 */
export function extractM2OFieldProps(staticInfo, dynamicInfo) {
    const { context, decorations, options, string, placeholder } = staticInfo;

    return {
        ...extractCreatePermissions(staticInfo),
        canOpen: !options.no_open,
        canScanBarcode: !!options.can_scan_barcode,
        canWrite: extractWritePermission(staticInfo),
        context: dynamicInfo.context,
        decorations,
        domain: dynamicInfo.domain,
        nameCreateField: options.create_name_field,
        openActionContext: context || "{}",
        placeholder,
        searchMemoization: options.search_memoization,
        searchThreshold: options.search_threshold,
        string,
    };
}

export class Many2OneField extends FieldComponent {
    static template = "web.Many2OneField";
    static components = { Many2One };
    static props = {
        ...standardFieldProps,
        canCreate: { type: Boolean, optional: true },
        canCreateEdit: { type: Boolean, optional: true },
        canOpen: { type: Boolean, optional: true },
        canQuickCreate: { type: Boolean, optional: true },
        canScanBarcode: { type: Boolean, optional: true },
        canWrite: { type: Boolean, optional: true },
        context: { type: Object, optional: true },
        decorations: { type: Object, optional: true },
        domain: { type: [Array, Function], optional: true },
        nameCreateField: { type: String, optional: true },
        openActionContext: { type: String, optional: true },
        placeholder: { type: String, optional: true },
        searchMemoization: { type: String, optional: true },
        searchThreshold: { type: Number, optional: true },
        string: { type: String, optional: true },
    };

    /** @returns {Record<string, any>} */
    get m2oProps() {
        return computeM2OProps(this.props);
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const many2OneField = {
    ...buildM2OFieldDescription(Many2OneField),
};
registerField("many2one", many2OneField);

registerField("res_partner_many2one", {
    ...buildM2OFieldDescription(Many2OneField),
});
