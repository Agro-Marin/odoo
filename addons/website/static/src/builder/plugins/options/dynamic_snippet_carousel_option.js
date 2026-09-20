/** @odoo-module native */
import { BaseOptionComponent } from "@html_builder/core/utils";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

import { useDynamicSnippetOption } from "./dynamic_snippet_hook.js";

const log = makeLogger("website.builder.option.dynamic_snippet_carousel_option");

export class DynamicSnippetCarouselOption extends BaseOptionComponent {
    static template = "website.DynamicSnippetCarouselOption";
    static dependencies = ["dynamicSnippetCarouselOption"];
    static selector = ".s_dynamic_snippet_carousel";

    setup() {
        super.setup();
        useLifecycleLog(log);
        const { getModelNameFilter } = this.dependencies.dynamicSnippetCarouselOption;
        this.dynamicOptionParams = useDynamicSnippetOption(getModelNameFilter());
    }
}
