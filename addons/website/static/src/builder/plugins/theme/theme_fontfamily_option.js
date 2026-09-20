/** @odoo-module native */
import { BuilderButton } from "@html_builder/core/building_blocks/builder_button";
import { BuilderFontFamilyPicker } from "@html_builder/core/building_blocks/builder_fontfamilypicker";
import { BaseOptionComponent, useDomState } from "@html_builder/core/utils";
import { getCSSVariableValue } from "@html_editor/utils/formatting";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

const log = makeLogger("website.builder.option.theme_fontfamily");

export class ThemeFontFamilyOption extends BaseOptionComponent {
    static template = "html_builder.ThemeFontFamilyOption";
    static props = {
        cssVariable: String,
        buttonIcon: String,
        buttonTitle: String,
    };
    static components = {
        BuilderFontFamilyPicker,
        BuilderButton,
    };

    setup() {
        super.setup();
        useLifecycleLog(log);
        const htmlStyle = this.env.editor.document.defaultView.getComputedStyle(
            this.env.getEditingElement(),
        );
        log.logic("setup isFontSpecified source", () => ({
            cssVariable: this.props.cssVariable,
            headings: this.props.cssVariable === "headings-font",
        }));
        if (this.props.cssVariable === "headings-font") {
            this.state = useDomState(() => ({
                isFontSpecified:
                    getCSSVariableValue("headings-font", htmlStyle) !==
                    getCSSVariableValue("default-headings-font", htmlStyle),
            }));
        } else {
            this.state = useDomState(() => ({
                isFontSpecified: !!getCSSVariableValue(
                    "set-" + this.props.cssVariable,
                    htmlStyle,
                ),
            }));
        }
    }
}
