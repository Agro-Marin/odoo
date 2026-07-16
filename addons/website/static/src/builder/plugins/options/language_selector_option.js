/** @odoo-module native */
import { BaseOptionComponent } from "@html_builder/core/utils";
import { after } from "@html_builder/utils/option_sequence";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { registry } from "@web/core/registry";

import { HEADER_BOX } from "./header/header_option_plugin.js";

export class LanguageSelectorOption extends BaseOptionComponent {
    static template = "website.LanguageSelectorOption";
    static selector = "#wrapwrap > header nav.navbar .o_header_language_selector";
    static groups = ["website.group_website_designer"];
    static editableOnly = false;
    static reloadTarget = true;
}

const LANGUAGE_SELECTOR = after(HEADER_BOX);
class LanguageSelectorOptionPlugin extends Plugin {
    static id = "languageSelectorOption";
    static dependencies = ["builderActions"];
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [withSequence(LANGUAGE_SELECTOR, LanguageSelectorOption)],
    };
}

registry
    .category("website-plugins")
    .add(LanguageSelectorOptionPlugin.id, LanguageSelectorOptionPlugin);
