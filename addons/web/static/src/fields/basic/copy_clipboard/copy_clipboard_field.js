// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/copy_clipboard/copy_clipboard_field */

import { Component } from "@odoo/owl";
import { CopyButton } from "@web/components/copy_button/copy_button";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { _t } from "@web/core/translation";
import { omit } from "@web/core/utils/collections/objects";
import { registerField } from "@web/fields/_registry";
import { CharField, charField } from "@web/fields/basic/char/char_field";
import { UrlField, urlField } from "@web/fields/basic/url/url_field";
import { standardFieldProps } from "@web/fields/standard_field_props";

class CopyClipboardField extends Component {
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
        return this.props.record.fields[this.props.name].type;
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
    // Getters, not snapshots. An addon may extend the wrapped field's props
    // after `web` has loaded -- `mail/js/onchange_on_keydown.js` reassigns
    // `CharField.props` and extends `charField.extractProps` in the same file --
    // and a `{ ...CharField.props }` evaluated at class-definition time freezes
    // them as they were before. The wrapper then received props it had never
    // declared (`onchangeOnKeydown`, `keydownDebounceDelay`) and Owl's prop
    // validation aborted the whole view: every `widget="CopyClipboardChar"`
    // raised "Oops! Something went wrong" in debug mode, which is where the
    // calendar quick-create dialog lives and why three calendar tours could not
    // get past their first step. Reading through on each validation keeps the
    // wrapper in step with whatever the wrapped field currently declares.
    static get props() {
        return { ...CopyClipboardField.props, ...CharField.props };
    }
    static get defaultProps() {
        return { ...CharField.defaultProps };
    }

    /** @returns {string} */
    get copyButtonIcon() {
        return "fa-clipboard";
    }
}

export class CopyClipboardURLField extends CopyClipboardField {
    static components = { Field: UrlField, CopyButton };
    // Getters for the same reason as the char variant above.
    static get props() {
        return { ...CopyClipboardField.props, ...UrlField.props };
    }
    static get defaultProps() {
        return { ...UrlField.defaultProps };
    }

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

export const copyClipboardButtonField = {
    component: CopyClipboardButtonField,
    displayName: _t("Copy to Clipboard"),
    // The button copies `record.data[name]` verbatim, so it only makes sense on
    // a value that is already a string.
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
        component,
        supportedTypes: wrapped.supportedTypes,
        supportedOptions: wrapped.supportedOptions,
        supportedAttributes: wrapped.supportedAttributes,
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
