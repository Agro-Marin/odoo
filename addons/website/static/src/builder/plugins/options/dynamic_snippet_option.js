/** @odoo-module native */
import { BaseOptionComponent } from "@html_builder/core/utils";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

import { useDynamicSnippetOption } from "./dynamic_snippet_hook.js";

const log = makeLogger("website.builder.option.dynamic_snippet_option");

export class DynamicSnippetOption extends BaseOptionComponent {
    static template = "website.DynamicSnippetOption";
    static dependencies = ["dynamicSnippetOption"];
    static selector = ".s_dynamic_snippet";
    static props = {
        slots: { type: Object, optional: true },
    };

    setup() {
        super.setup();
        useLifecycleLog(log);
        const { getModelNameFilter } = this.dependencies.dynamicSnippetOption;
        this.dynamicOptionParams = useDynamicSnippetOption(getModelNameFilter());
    }
}
