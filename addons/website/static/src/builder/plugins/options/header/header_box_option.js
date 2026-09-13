/** @odoo-module native */
import { BaseOptionComponent, useDomState } from "@html_builder/core/utils";
import { BorderConfigurator } from "@html_builder/plugins/border_configurator_option";
import { ShadowOption } from "@html_builder/plugins/shadow_option";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

import { basicHeaderOptionSettings } from "./basicHeaderOptionSettings.js";

const log = makeLogger("website.builder.option.header_box_option");

export class HeaderBoxOption extends BaseOptionComponent {
    static template = "website.HeaderBoxOption";
    static applyTo = ".navbar:not(.d-none)";

    static components = { BorderConfigurator, ShadowOption };

    setup() {
        super.setup();
        useLifecycleLog(log);
        this.domState = useDomState((editingElement) => ({
            withRoundCorner: !editingElement.classList.contains(
                "o_header_force_no_radius",
            ),
        }));
    }
}

Object.assign(HeaderBoxOption, basicHeaderOptionSettings);
