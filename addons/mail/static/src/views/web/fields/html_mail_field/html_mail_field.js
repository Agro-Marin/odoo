/** @odoo-module native */
import { HtmlField, htmlField } from "@html_editor/fields/html_field";
import { ColumnPlugin } from "@html_editor/main/column_plugin";
import { registry } from "@web/core/registry";

import { getCSSRules, toInline } from "./convert_inline.js";
/** @type {WeakMap<Element, Object[]>} */
const cssRulesByElement = new WeakMap();

export class HtmlMailField extends HtmlField {
    /**
     * @param {WeakMap} cssRulesByElement
     * @param {Editor} editor
     * @param {HTMLElement} el
     */
    static async getInlinedEditorContent(cssRulesByElement, editor, el) {
        if (!cssRulesByElement.has(editor.editable)) {
            cssRulesByElement.set(editor.editable, getCSSRules(editor.document));
        }
        const cssRules = cssRulesByElement.get(editor.editable);
        editor.editable.after(el);
        el.classList.remove("odoo-editor-editable");
        try {
            await toInline(el, cssRules);
        } finally {
            el.remove();
        }
    }

    async getEditorContent() {
        const el = await super.getEditorContent();
        if (this.editor.editable) {
            await HtmlMailField.getInlinedEditorContent(
                cssRulesByElement,
                this.editor,
                el,
            );
        }
        return el;
    }

    getConfig() {
        const config = super.getConfig();
        config.dropImageAsAttachment = false;
        config.defaultLinkAttributes = { target: "_blank", rel: "noreferrer noopener" };
        config.Plugins = config.Plugins.filter((plugin) => plugin !== ColumnPlugin);
        return config;
    }
}

export const htmlMailField = {
    ...htmlField,
    component: HtmlMailField,
    additionalClasses: ["o_field_html"],
    /**
     * @param {Object} fieldInfo
     * @param {Object} fieldInfo.attrs
     * @param {Object} fieldInfo.options
     * @param {Object} dynamicInfo
     * @returns {Object}
     */
    extractProps({ attrs, options }, dynamicInfo) {
        const props = htmlField.extractProps({ attrs, options }, dynamicInfo);
        props.embeddedComponents = false;
        return props;
    },
};

registry.category("fields").add("html_mail", htmlMailField);
