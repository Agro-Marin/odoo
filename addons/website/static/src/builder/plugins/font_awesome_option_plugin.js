/** @odoo-module native */
import { ClassAction } from "@html_builder/core/core_builder_action_plugin";
import { BaseOptionComponent } from "@html_builder/core/utils";
import { BorderConfigurator } from "@html_builder/plugins/border_configurator_option";
import { FONT_AWESOME } from "@html_builder/utils/option_sequence";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";

const log = makeLogger("website.builder.plugin.font_awesome_option_plugin");

export class FontAwesomeOption extends BaseOptionComponent {
    static template = "website.FontAwesomeOption";
    static selector = ":is(span, i):is(.fa-solid, .fa-regular, .fa-brands)";
    static exclude = "[data-oe-xpath]";
    static components = { BorderConfigurator };
}

class FontAwesomeOptionPlugin extends Plugin {
    static id = "fontAwesomeOptionPlugin";
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [withSequence(FONT_AWESOME, FontAwesomeOption)],
        builder_actions: {
            FaResizeAction,
        },
    };
}

export class FaResizeAction extends ClassAction {
    static id = "faResize";
    apply(context) {
        const { editingElement } = context;
        log.pipeline("FaResizeAction apply", () => ({
            className: editingElement.className,
            isPreviewing: context.isPreviewing,
        }));
        editingElement.classList.remove("fa-1x", "fa-lg");
        super.apply(context);
    }
}

registry
    .category("website-plugins")
    .add(FontAwesomeOptionPlugin.id, FontAwesomeOptionPlugin);
