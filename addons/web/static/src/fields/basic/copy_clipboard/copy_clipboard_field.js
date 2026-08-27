// @ts-check
/** @odoo-module native */

import { CopyButton } from "@web/components/copy_button/copy_button";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { _t } from "@web/core/translation";
import { omit } from "@web/core/utils/collections/objects";
import { registerField } from "@web/fields/_registry";
import { CharField, charField } from "@web/fields/basic/char/char_field";
import { UrlField, urlField } from "@web/fields/basic/url/url_field";
import { FieldComponent } from "@web/fields/field_component";
import { archAttribute } from "@web/fields/field_options";
import { standardFieldProps } from "@web/fields/standard_field_props";

class CopyClipboardField extends FieldComponent {
    static template = "web.CopyClipboardField";
    static props = {
        ...standardFieldProps,
        string: { type: String, optional: true },
        disabledExpr: { type: String, optional: true },
    };

    setup() {
        this.copyText = this.props.string || _t("Copy");
        this.successText = _t("Copied");
    }

    /** @returns {string} */
    get copyButtonClassName() {
        return `o_btn_${this.type}_copy btn-sm`;
    }
    /** @returns {Object} */
    get fieldProps() {
        return omit(this.props, "string", "disabledExpr");
    }
    /** @returns {string} */
    get type() {
        return this.field.type;
    }
    /** @returns {boolean} */
    get disabled() {
        return this.props.disabledExpr
            ? evaluateBooleanExpr(
                  this.props.disabledExpr,
                  this.props.record.evalContextWithVirtualIds,
              )
            : false;
    }
}

export class CopyClipboardButtonField extends CopyClipboardField {
    static template = "web.CopyClipboardButtonField";
    static components = { CopyButton };
    static props = {
        ...CopyClipboardField.props,
        btnClass: { type: String, optional: true },
    };
    static defaultProps = {
        ...CopyClipboardField.defaultProps,
        btnClass: "primary",
    };

    get copyButtonClassName() {
        return `o_btn_${this.type}_copy btn-${this.props.btnClass} rounded-2`;
    }
}

export class CopyClipboardCharField extends CopyClipboardField {
    static components = { Field: CharField, CopyButton };
    // A getter, not a snapshot: `mail` REASSIGNS `CharField.props` /
    // `UrlField.props` at module load to add its onchange-on-keydown props,
    // while `buildCopyClipboardField` captures the registry entry by
    // reference and so supplies those props at render time. Spread once at
    // class-definition time, the schema never saw them and Owl rejected
    // every render as invalid props.
    static get props() {
        return { ...CopyClipboardField.props, ...CharField.props };
    }
    static defaultProps = {
        ...CopyClipboardField.defaultProps,
        ...CharField.defaultProps,
    };

    /** @returns {string} */
    get copyButtonIcon() {
        return "fa-clipboard";
    }
}

export class CopyClipboardURLField extends CopyClipboardField {
    static components = { Field: UrlField, CopyButton };
    // A getter, not a snapshot: `mail` REASSIGNS `CharField.props` /
    // `UrlField.props` at module load to add its onchange-on-keydown props,
    // while `buildCopyClipboardField` captures the registry entry by
    // reference and so supplies those props at render time. Spread once at
    // class-definition time, the schema never saw them and Owl rejected
    // every render as invalid props.
    static get props() {
        return { ...CopyClipboardField.props, ...UrlField.props };
    }
    static defaultProps = {
        ...CopyClipboardField.defaultProps,
        ...UrlField.defaultProps,
    };

    /** @returns {string} */
    get copyButtonIcon() {
        return "fa-link";
    }
}

/**
 * @param {{ string?: string, attrs: Record<string, string> }} fieldInfo
 * @returns {{ string?: string, disabledExpr?: string }}
 */
function extractProps({ string, attrs }) {
    return {
        string,
        disabledExpr: attrs.disabled,
    };
}

/**
 * @type {import("registries").FieldsRegistryItemShape["supportedAttributes"]}
 */
const copyClipboardAttributes = [
    archAttribute("disabled", _t("Disabled when"), {
        help: _t("Python expression; when it is true the copy button is inert."),
    }),
];

export const copyClipboardButtonField = {
    component: CopyClipboardButtonField,
    displayName: _t("Copy to Clipboard"),
    supportedAttributes: copyClipboardAttributes,
    supportedTypes: ["char", "text"],
    supportedOptions: [
        {
            label: _t("Button style"),
            name: "btn_class",
            type: "string",
            help: _t("Bootstrap button variant, e.g. 'primary' or 'secondary'."),
        },
    ],
    extractProps: (/** @type {any} */ fieldInfo) => ({
        ...extractProps(fieldInfo),
        btnClass: fieldInfo.options.btn_class,
    }),
};

registerField("CopyClipboardButton", copyClipboardButtonField);

/**
 * @param {import("@odoo/owl").ComponentConstructor} component
 * @param {Record<string, any>} wrapped
 * @returns {Record<string, any>}
 */
function buildCopyClipboardField(component, wrapped) {
    return {
        // Spread, never a hand-picked list of keys: picking four of them
        // silently dropped `fieldDependencies`, and with it the `render_model`
        // that `dynamic_placeholder` needs, so the picker refused to open on a
        // CopyClipboardChar. `isEmpty`, `listViewWidth`, `relatedFields` and
        // `additionalClasses` were going the same way for the next widget that
        // grew one.
        ...wrapped,
        component,
        supportedAttributes: [
            ...copyClipboardAttributes,
            ...(wrapped.supportedAttributes || []),
        ],
        extractProps: (
            /** @type {any} */ fieldInfo,
            /** @type {any} */ dynamicInfo,
        ) => ({
            ...wrapped.extractProps?.(fieldInfo, dynamicInfo),
            ...extractProps(fieldInfo),
        }),
    };
}

export const copyClipboardCharField = {
    ...buildCopyClipboardField(CopyClipboardCharField, charField),
    displayName: _t("Copy Text to Clipboard"),
};

registerField("CopyClipboardChar", copyClipboardCharField);

export const copyClipboardURLField = {
    ...buildCopyClipboardField(CopyClipboardURLField, urlField),
    displayName: _t("Copy URL to Clipboard"),
};

registerField("CopyClipboardURL", copyClipboardURLField);
