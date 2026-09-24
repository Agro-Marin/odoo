// @ts-check
/** @odoo-module native */

import { useState } from "@odoo/owl";
import { FormRenderer } from "@web/views/form/form_renderer";
import { useSettingsSearchContext } from "@web/views/settings/settings_search_context";

import { FormLabelHighlightText } from "./highlight_text/form_label_highlight_text.js";
import { HighlightText } from "./highlight_text/highlight_text.js";
import { SearchableSetting } from "./settings/searchable_setting.js";
import { SettingHeader } from "./settings/setting_header.js";
import { SettingsApp } from "./settings/settings_app.js";
import { SettingsBlock } from "./settings/settings_block.js";
import { SettingsPage } from "./settings/settings_page.js";
export class SettingsFormRenderer extends FormRenderer {
    static components = {
        .../** @type {any} */ (FormRenderer).components,
        SearchableSetting,
        SettingHeader,
        SettingsBlock,
        SettingsPage,
        SettingsApp,
        HighlightText,
        FormLabel: FormLabelHighlightText,
    };
    static props = {
        .../** @type {any} */ (FormRenderer).props,
        initialApp: String,
        slots: Object,
    };

    setup() {
        super.setup();
        this.settingsContext = useSettingsSearchContext();
        this.searchState = useState(this.settingsContext.searchState);
    }

    get shouldAutoFocus() {
        return false;
    }
}
