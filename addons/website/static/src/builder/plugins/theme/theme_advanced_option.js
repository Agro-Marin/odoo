/** @odoo-module native */
import { BaseOptionComponent } from "@html_builder/core/utils";
import { useState } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { _t } from "@web/core/translation";

const log = makeLogger("website.builder.option.theme_advanced");

export class ThemeAdvancedOption extends BaseOptionComponent {
    static template = "website.ThemeAdvancedOption";
    static dependencies = ["themeTab"];
    setup() {
        super.setup();
        useLifecycleLog(log);
        this.grays = useState(this.dependencies.themeTab.getGrays());
    }

    getGrayTitle(grayCode) {
        return _t("Gray %(grayCode)s", { grayCode });
    }
}
