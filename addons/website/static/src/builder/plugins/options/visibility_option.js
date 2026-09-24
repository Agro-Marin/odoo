/** @odoo-module native */
import { BaseOptionComponent } from "@html_builder/core/utils";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { useServices } from "@web/core/utils/hooks";

const log = makeLogger("website.builder.option.visibility_option");

export class VisibilityOption extends BaseOptionComponent {
    static template = "website.VisibilityOption";
    static dependencies = ["visibility", "websiteSession"];
    static selector = "section, .s_hr";

    setup() {
        super.setup();
        this.appServices = useServices();
        useLifecycleLog(log);
        this.websiteSession = this.dependencies.websiteSession.getSession();
    }
}
