/** @odoo-module native */
import { BaseOptionComponent } from "@html_builder/core/utils";

import { basicHeaderOptionSettings } from "./basicHeaderOptionSettings.js";

export class HeaderIconBackgroundOption extends BaseOptionComponent {
    static template = "website.HeaderIconBackgroundOption";
}

Object.assign(HeaderIconBackgroundOption, basicHeaderOptionSettings);
