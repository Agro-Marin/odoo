/** @odoo-module native */
import { BaseOptionComponent } from "@html_builder/core/utils";
import { onWillStart } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

const log = makeLogger("website.builder.option.switchable_views");

export class SwitchableViews extends BaseOptionComponent {
    static template = "website.SwitchableViews";
    static dependencies = ["switchableViews"];
    static selector = ".o_portal_wrap";
    static groups = ["website.group_website_designer"];
    static editableOnly = false;

    setup() {
        super.setup();
        useLifecycleLog(log);
        const { getSwitchableRelatedViews } = this.dependencies.switchableViews;
        onWillStart(async () => {
            const endViews = log.perf("SwitchableViews load related views");
            this.switchableRelatedViews = await getSwitchableRelatedViews();
            endViews(() => ({ count: this.switchableRelatedViews.length }));
        });
    }
}
