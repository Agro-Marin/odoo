/** @odoo-module native */
import { BaseOptionComponent } from "@html_builder/core/utils";

import { ThemeFontFamilyOption } from "./theme_fontfamily_option.js";

export class ThemeHeadingsOption extends BaseOptionComponent {
    static template = "website.ThemeHeadingsOption";
    static components = {
        ThemeFontFamilyOption,
    };
}
