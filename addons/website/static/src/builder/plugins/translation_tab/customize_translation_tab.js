/** @odoo-module native */
import { OptionsContainer } from "@html_builder/sidebar/option_container";
import { Component } from "@odoo/owl";

export class CustomizeTranslationTab extends Component {
    static template = "website.CustomizeTranslationTab";
    static components = { OptionsContainer };
    static props = {};
    setup() {
        this.optionsContainers = this.env.editor.resources["translate_options"];
    }
}
