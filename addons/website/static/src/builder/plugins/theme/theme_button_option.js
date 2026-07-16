/** @odoo-module native */
import { BaseOptionComponent } from "@html_builder/core/utils";

import { ThemeFontFamilyOption } from "./theme_fontfamily_option.js";

export class ThemeButtonOption extends BaseOptionComponent {
    static template = "website.ThemeButtonOption";
    static components = {
        ThemeFontFamilyOption,
    };
}
