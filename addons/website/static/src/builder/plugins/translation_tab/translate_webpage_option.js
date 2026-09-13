/** @odoo-module native */
import { BaseOptionComponent } from "@html_builder/core/utils";
import { useState } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

const log = makeLogger("website.builder.option.translate_webpage_option");

export class TranslateWebpageOption extends BaseOptionComponent {
    static template = "website.TranslateWebpageOption";
    static selector = "*";
    setup() {
        super.setup();
        useLifecycleLog(log);
        this.translationState = useState(
            this.env.editor.shared.customizeTranslationTab.getTranslationState(),
        );
    }
}
