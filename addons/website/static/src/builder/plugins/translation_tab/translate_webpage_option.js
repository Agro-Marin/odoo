/** @odoo-module native */
import { useBuilderContext } from "@html_builder/core/builder_context";
import { BaseOptionComponent } from "@html_builder/core/utils";
import { useState } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { useServices } from "@web/core/utils/hooks";

const log = makeLogger("website.builder.option.translate_webpage_option");

export class TranslateWebpageOption extends BaseOptionComponent {
    static template = "website.TranslateWebpageOption";
    static selector = "*";
    setup() {
        super.setup();
        this.appServices = useServices();
        this.builderContext = useBuilderContext();
        useLifecycleLog(log);
        this.translationState = useState(
            this.builderContext.editor.shared.customizeTranslationTab.getTranslationState(),
        );
    }
}
