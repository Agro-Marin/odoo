// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/copy_clipboard/copy_clipboard_field - Wrapper field that adds a copy-to-clipboard button to Char/URL fields */

import { Component } from "@odoo/owl";
import { CopyButton } from "@web/components/copy_button/copy_button";
import { _t } from "@web/core/l10n/translation";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
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

    /** @returns {string} CSS class for the copy button */
    get copyButtonClassName() {
        return `o_btn_${this.type}_copy btn-sm`;
    }
    /** @returns {Object} Props forwarded to the inner field component */
    get fieldProps() {
        return omit(this.props, "string", "disabledExpr");
    }
    /** @returns {string} ORM field type */
    get type() {
        return this.props.record.fields[this.props.name].type;
    }
    /** @returns {boolean} Whether the copy button is disabled (from expression evaluation) */
    get disabled() {
        return this.props.disabledExpr
            ? evaluateBooleanExpr(
                  this.props.disabledExpr,
                  this.props.record.evalContextWithVirtualIds,
              )
            : false;
    }
}

/** Copy-to-clipboard variant rendered as a standalone button. */
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
    static props = { ...CopyClipboardField.props, ...CharField.props };
    static defaultProps = { ...CharField.defaultProps };

    /** @returns {string} Font Awesome icon class */
    get copyButtonIcon() {
        return "fa-clipboard";
    }
}

export class CopyClipboardURLField extends CopyClipboardField {
    static components = { Field: UrlField, CopyButton };
    static props = { ...CopyClipboardField.props, ...UrlField.props };
    static defaultProps = { ...UrlField.defaultProps };

    /** @returns {string} Font Awesome icon class */
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
    extractProps: (fieldInfo) => ({
        ...extractProps(fieldInfo),
        btnClass: fieldInfo.options.btn_class,
    }),
};

registerField("CopyClipboardButton", copyClipboardButtonField);

/**
 * Build the descriptor for a copy-to-clipboard wrapper around an existing
 * field descriptor.
 *
 * The wrapper renders the wrapped widget and forwards it ``fieldProps``, so it
 * has to CARRY that widget's props — and therefore has to run that widget's
 * own ``extractProps``. Declaring only ``{string, disabledExpr}`` meant every
 * option and attribute the inner widget understands was silently dropped:
 * ``<field widget="CopyClipboardChar" placeholder="…"/>`` rendered no
 * placeholder, and ``password``, ``autocomplete``, the dynamic-placeholder
 * options (char) and ``website_path``/``text`` (url) were all inert. They are
 * all optional props, so nothing ever raised.
 *
 * ``supportedOptions``/``supportedAttributes`` are inherited for the same
 * reason: the wrapper accepts exactly what the wrapped widget accepts, and
 * restating the list would let the two drift.
 *
 * @param {import("@odoo/owl").ComponentConstructor} component
 * @param {Record<string, any>} wrapped the wrapped widget's descriptor
 * @returns {Record<string, any>}
 */
function buildCopyClipboardField(component, wrapped) {
    return {
        component,
        supportedTypes: wrapped.supportedTypes,
        supportedOptions: wrapped.supportedOptions,
        supportedAttributes: wrapped.supportedAttributes,
        extractProps: (fieldInfo, dynamicInfo) => ({
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
