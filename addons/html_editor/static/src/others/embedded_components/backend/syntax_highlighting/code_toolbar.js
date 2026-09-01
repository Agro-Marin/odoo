/** @odoo-module native */
import { Component } from "@odoo/owl";
import { CopyButton } from "@web/components/copy_button";
import { Dropdown, DropdownItem } from "@web/components/dropdown";
import { _t } from "@web/core/translation";

export const LANGUAGES = {
    plaintext: _t("Plain Text"),
    markdown: _t("Markdown"),
    javascript: _t("Javascript"),
    typescript: _t("Typescript"),
    jsdoc: _t("JSDoc"),
    java: _t("Java"),
    python: _t("Python"),
    html: _t("HTML"),
    xml: _t("XML"),
    svg: _t("SVG"),
    json: _t("JSON"),
    css: _t("CSS"),
    sass: _t("SASS"),
    scss: _t("SCSS"),
    sql: _t("SQL"),
    diff: _t("Diff"),
};

export class CodeToolbar extends Component {
    static template = "html_editor.CodeToolbar";
    static props = {
        target: { validate: (el) => el.nodeType === Node.ELEMENT_NODE },
        getContent: { type: Function },
        onLanguageChange: { type: Function },
        currentLanguage: { type: String },
        convertToParagraph: { type: Function },
        toggleCodeWrap: { type: Function },
    };
    static components = { Dropdown, DropdownItem, CopyButton };

    setup() {
        super.setup();
        this.languages = LANGUAGES;
    }
}
