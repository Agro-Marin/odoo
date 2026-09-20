/** @odoo-module native */
import { BaseOptionComponent, useDomState } from "@html_builder/core/utils";
import { useBackgroundOption } from "@html_builder/plugins/background_option/background_hook";
import { BackgroundOption } from "@html_builder/plugins/background_option/background_option";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

import { ParallaxOption } from "./parallax_option.js";

const log = makeLogger("website.builder.option.background_option");

export class BaseWebsiteBackgroundOption extends BaseOptionComponent {
    static template = "website.WebsiteBackgroundOption";
    static components = {
        ...BackgroundOption.components,
        ParallaxOption,
    };
    static props = {
        ...BackgroundOption.props,
        withColors: { type: Boolean, optional: true },
        withImages: { type: Boolean, optional: true },
        withColorCombinations: { type: Boolean, optional: true },
        withVideos: { type: Boolean, optional: true },
    };
    static defaultProps = {
        ...BackgroundOption.defaultProps,
        withColors: true,
        withImages: true,
        withColorCombinations: true,
        withVideos: false,
    };
    setup() {
        super.setup();
        useLifecycleLog(log);
        const { showColorFilter } = useBackgroundOption(this.isActiveItem);
        this.showColorFilter = () =>
            showColorFilter() || this.isActiveItem("toggle_bg_video_id");
        this.websiteBgOptionDomState = useDomState((el) => ({
            applyTo: el.querySelector(":scope > .s_parallax_bg")
                ? ".s_parallax_bg"
                : "",
        }));
    }
}
