// @ts-check
/** @odoo-module native */

import { _t } from "@web/core/translation";

/** @import { FieldsRegistryItemShape } from "registries" */

/**
 * @param {string} name
 * @param {string} label
 * @param {{ type?: string, help?: string, availableTypes?: string[] }} [rest]
 * @returns {NonNullable<FieldsRegistryItemShape["supportedAttributes"]>[number]}
 */
export function archAttribute(name, label, rest = {}) {
    return { name, label, type: "string", ...rest };
}

/**
 * @returns {NonNullable<FieldsRegistryItemShape["supportedAttributes"]>[number]}
 */
export function digitsAttribute() {
    return archAttribute("digits", _t("Digits"), {
        help: _t(
            "Precision as a `[total, decimals]` pair, e.g. `[16,2]`. Overrides the field's own digits.",
        ),
    });
}

/**
 * @returns {NonNullable<FieldsRegistryItemShape["supportedAttributes"]>[number]}
 */
export function createPermissionAttribute() {
    return archAttribute("can_create", _t("Can create"), {
        type: "boolean",
        help: _t(
            "Python expression; when it is false the dropdown offers no creation at all.",
        ),
    });
}

/**
 * @returns {NonNullable<FieldsRegistryItemShape["supportedAttributes"]>[number]}
 */
export function writePermissionAttribute() {
    return archAttribute("can_write", _t("Can write"), {
        type: "boolean",
        help: _t(
            "Python expression; when it is false the linked record cannot be edited from here.",
        ),
    });
}

/**
 * @returns {NonNullable<FieldsRegistryItemShape["supportedAttributes"]>}
 */
export function relationalPermissionAttributes() {
    return [createPermissionAttribute(), writePermissionAttribute()];
}

/**
 * @returns {NonNullable<FieldsRegistryItemShape["supportedAttributes"]>[number]}
 */
export function filenameAttribute() {
    return archAttribute("filename", _t("File name field"), {
        type: "field",
        availableTypes: ["char"],
        help: _t("Char field holding the name the file is downloaded under."),
    });
}

/**
 * @returns {NonNullable<FieldsRegistryItemShape["supportedAttributes"]>}
 */
export function imageDimensionAttributes() {
    return [
        archAttribute("width", _t("Width"), {
            type: "number",
            help: _t("Width in pixels. Ignored when the `size` option is set."),
        }),
        archAttribute("height", _t("Height"), {
            type: "number",
            help: _t("Height in pixels. Ignored when the `size` option is set."),
        }),
    ];
}

/**
 * @param {string[]} [availableTypes=["char"]]
 * @returns {NonNullable<FieldsRegistryItemShape["supportedOptions"]>[number]}
 */
export function placeholderFieldOption(availableTypes = ["char"]) {
    return {
        label: _t("Dynamic Placeholder"),
        name: "placeholder_field",
        type: "field",
        availableTypes,
        help: _t(
            "Displays the value of the selected field as a textual hint. If the selected field is empty, the static placeholder attribute is displayed instead.",
        ),
    };
}

/**
 * @returns {NonNullable<FieldsRegistryItemShape["supportedOptions"]>}
 */
export function datePrecisionOptions() {
    const choices = () => [
        { label: _t("Days"), value: "days" },
        { label: _t("Months"), value: "months" },
        { label: _t("Years"), value: "years" },
        { label: _t("Decades"), value: "decades" },
    ];
    return [
        {
            label: _t("Minimal precision"),
            name: "min_precision",
            type: "selection",
            help: _t(
                "Choose which minimal precision (days, months, ...) you want in the datetime picker.",
            ),
            choices: choices(),
        },
        {
            label: _t("Maximal precision"),
            name: "max_precision",
            type: "selection",
            help: _t(
                "Choose which maximal precision (days, months, ...) you want in the datetime picker.",
            ),
            choices: choices(),
        },
    ];
}

/**
 * @returns {NonNullable<FieldsRegistryItemShape["supportedOptions"]>}
 */
export function dynamicPlaceholderOptions() {
    return [
        {
            label: _t("Dynamic Placeholder"),
            name: "dynamic_placeholder",
            type: "boolean",
            help: _t(
                "Offer a picker that inserts a {{object.field}} expression into the text.",
            ),
        },
        {
            label: _t("Dynamic Placeholder model reference"),
            name: "dynamic_placeholder_model_reference_field",
            type: "field",
            availableTypes: ["char"],
            help: _t("Field holding the model name whose fields the picker offers."),
        },
    ];
}

/**
 * @returns {NonNullable<FieldsRegistryItemShape["supportedOptions"]>[number]}
 */
export function autosaveOption() {
    return {
        label: _t("Autosave"),
        name: "autosave",
        type: "boolean",
        default: true,
        help: _t(
            "If checked, the record will be saved immediately when the field is modified.",
        ),
    };
}

/**
 * @returns {NonNullable<FieldsRegistryItemShape["supportedOptions"]>[number]}
 */
export function enableFormattingOption() {
    return {
        label: _t("Format number"),
        name: "enable_formatting",
        type: "boolean",
        help: _t(
            "Format the value according to your language setup - e.g. thousand separators, rounding, etc.",
        ),
        default: true,
    };
}

/**
 * @returns {NonNullable<FieldsRegistryItemShape["supportedOptions"]>}
 */
export function numericInputOptions() {
    return [
        {
            label: _t("Type"),
            name: "type",
            type: "string",
        },
        {
            label: _t("Step"),
            name: "step",
            type: "number",
        },
    ];
}

/**
 * @returns {NonNullable<FieldsRegistryItemShape["supportedOptions"]>[number]}
 */
export function imageSizeOption() {
    return {
        label: _t("Size"),
        name: "size",
        type: "selection",
        choices: [
            { label: _t("Small"), value: "[0,90]" },
            { label: _t("Medium"), value: "[0,180]" },
            { label: _t("Large"), value: "[0,270]" },
        ],
    };
}

/**
 * @returns {NonNullable<FieldsRegistryItemShape["supportedOptions"]>[number]}
 */
export function acceptedFileExtensionsOption() {
    return {
        label: _t("Accepted file extensions"),
        name: "accepted_file_extensions",
        type: "string",
        help: _t(
            "Comma-separated list the file picker filters on, e.g. `.png,.jpg` or `image/*`.",
        ),
    };
}

/**
 * @returns {NonNullable<FieldsRegistryItemShape["supportedOptions"]>}
 */
export function humanReadableOptions() {
    return [
        {
            label: _t("User-friendly format"),
            name: "human_readable",
            type: "boolean",
            help: _t(
                "Use a human readable format (e.g.: 500G instead of 500,000,000,000).",
            ),
        },
        {
            label: _t("Decimals"),
            name: "decimals",
            type: "number",
            default: 0,
            help: _t(
                "Use it with the 'User-friendly format' option to customize the formatting.",
            ),
        },
    ];
}

/**
 * @returns {NonNullable<FieldsRegistryItemShape["supportedOptions"]>[number]}
 */
export function hideTrailingZerosOption() {
    return {
        label: _t("Hide trailing zeros"),
        name: "hide_trailing_zeros",
        type: "boolean",
        help: _t(
            "Hide zeros to the right of the last non-zero digit, e.g. 1.20 becomes 1.2",
        ),
    };
}

/**
 * @param {string} help
 * @param {{ isRelationalField?: boolean }} [options]
 * @returns {NonNullable<FieldsRegistryItemShape["supportedOptions"]>[number]}
 */
export function colorFieldOption(help, { isRelationalField = false } = {}) {
    return {
        label: _t("Color field"),
        name: "color_field",
        type: "field",
        availableTypes: ["integer"],
        ...(isRelationalField ? { isRelationalField: true } : {}),
        help,
    };
}

/**
 * @returns {NonNullable<FieldsRegistryItemShape["fieldDependencies"]>}
 */
export function dynamicPlaceholderDependency() {
    // `useDynamicPlaceholder.updateModel` reads these out of `record.data` to
    // decide which model's fields the picker offers. `render_model` is the
    // server's own answer (`mixin.mail.render._compute_render_model`) and needs
    // no declaration in the view; a view may still name a field, which wins.
    // Each is `optional`, so a model that has neither simply drops it.
    return ({ options }) => [
        ...(options?.dynamic_placeholder
            ? [
                  { name: "render_model", optional: true, readonly: true },
                  { name: "model", optional: true, readonly: true },
              ]
            : []),
        ...(options?.dynamic_placeholder_model_reference_field
            ? [
                  {
                      name: options.dynamic_placeholder_model_reference_field,
                      optional: true,
                      readonly: true,
                  },
              ]
            : []),
    ];
}
