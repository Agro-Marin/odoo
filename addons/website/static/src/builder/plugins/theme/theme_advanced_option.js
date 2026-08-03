/** @odoo-module native */
import { BaseOptionComponent } from "@html_builder/core/utils";
import { useState } from "@odoo/owl";
import { _t } from "@web/core/translation";

export class ThemeAdvancedOption extends BaseOptionComponent {
    static template = "website.ThemeAdvancedOption";
    static dependencies = ["themeTab"];
    setup() {
        super.setup();
        this.grays = useState(this.dependencies.themeTab.getGrays());
    }

    getGrayTitle(grayCode) {
        return _t("Gray %(grayCode)s", { grayCode });
    }
}
