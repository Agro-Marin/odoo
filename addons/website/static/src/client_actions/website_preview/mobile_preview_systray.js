/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { useService } from "@web/core/utils/hooks";

const log = makeLogger("website.systray.mobile_preview");

export class MobilePreviewSystrayItem extends Component {
    static template = "website.MobilePreviewSystrayItem";
    static props = {};
    setup() {
        useLifecycleLog(log);
        this.websiteService = useService("website");
        this.state = useState(this.websiteService.context);
    }

    onClick() {
        log.logic("toggle mobile preview", () => ({
            toMobile: !this.websiteService.context.isMobile,
        }));
        this.websiteService.context.isMobile = !this.websiteService.context.isMobile;
    }
}
