/** @odoo-module native */
import { useBuilderContext } from "@html_builder/core/builder_context";
import { OptionsContainer } from "@html_builder/sidebar/option_container";
import { useOptionsSubEnv } from "@html_builder/utils/utils";
import { Component, useState, useSubEnv } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

const log = makeLogger("website.builder.option.theme_tab");

export class ThemeTab extends Component {
    static template = "website.ThemeTab";
    static components = { OptionsContainer };
    static props = {
        colorPresetToShow: { type: Number | null, optional: true },
    };
    static defaultProps = {};

    setup() {
        useLifecycleLog(log);
        useOptionsSubEnv(() => [this.builderContext.editor.document.body]);
        useSubEnv({
            colorPresetToShow: this.props.colorPresetToShow,
        });
        this.builderContext = useBuilderContext();
        this.state = useState({
            fontsData: {},
        });
        this.optionsContainers = this.builderContext.editor.resources["theme_options"];
        log.pipeline("setup theme option containers", () => ({
            count: this.optionsContainers?.length,
            colorPresetToShow: this.props.colorPresetToShow,
        }));
    }
}
