/** @odoo-module native */
import { useBuilderContext } from "@html_builder/core/builder_context";
import { OptionsContainer } from "@html_builder/sidebar/option_container";
import { useOptionsSubEnv } from "@html_builder/utils/utils";
import { Component, useState } from "@odoo/owl";

export class DesignTab extends Component {
    static template = "mass_mailing.DesignTab";
    static components = { OptionsContainer };
    static props = {
        colorPresetToShow: { optional: true },
    };

    setup() {
        useOptionsSubEnv(() => [this.builderContext.editor.document.body]);
        this.builderContext = useBuilderContext();
        this.state = useState({
            fontsData: {},
        });
        this.optionsContainers = this.builderContext.editor.resources["design_options"];
    }
}
