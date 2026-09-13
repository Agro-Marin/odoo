/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { registry } from "@web/core/registry";
import { useBus } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/fields/standard_field_props";

const log = makeLogger("website.field.widget_iframe");

class FieldIframePreview extends Component {
    static template = "website.iframeWidget";
    static props = { ...standardFieldProps };
    setup() {
        useLifecycleLog(log);
        this.state = useState({ isMobile: false });

        useBus(this.env.bus, "THEME_PREVIEW:SWITCH_MODE", (ev) => {
            log.logic("THEME_PREVIEW:SWITCH_MODE", () => ({ mode: ev.detail.mode }));
            this.state.isMobile = ev.detail.mode === "mobile";
        });
    }
}

export const fieldIframePreview = {
    component: FieldIframePreview,
};

registry.category("fields").add("iframe", fieldIframePreview);
