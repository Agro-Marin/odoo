/** @odoo-module native */
import { OptionsContainer } from "@html_builder/sidebar/option_container";
import { Component } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

const log = makeLogger("website.builder.translation.customize_translation_tab");

export class CustomizeTranslationTab extends Component {
    static template = "website.CustomizeTranslationTab";
    static components = { OptionsContainer };
    static props = {};
    setup() {
        useLifecycleLog(log);
        this.optionsContainers = this.env.editor.resources["translate_options"];
    }
}
