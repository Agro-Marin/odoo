/** @odoo-module native */
import { BaseOptionComponent } from "@html_builder/core/utils";
import { BorderConfigurator } from "@html_builder/plugins/border_configurator_option";
import { ShadowOption } from "@html_builder/plugins/shadow_option";
import { after } from "@html_builder/utils/option_sequence";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { registry } from "@web/core/registry";
import { WEBSITE_BACKGROUND_OPTIONS } from "@website/builder/option_sequence";

export class BentoBorderOption extends BaseOptionComponent {
    static template = "html_builder.BentoBorderOption";
    static selector = ".s_bento_banner section[data-name='Card'], .s_bento_block_card";
    static components = { BorderConfigurator, ShadowOption };
}

class BentoBorderOptionPlugin extends Plugin {
    static id = "BentoBorderOption";
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [
            withSequence(after(WEBSITE_BACKGROUND_OPTIONS), BentoBorderOption),
        ],
    };
}
registry
    .category("website-plugins")
    .add(BentoBorderOptionPlugin.id, BentoBorderOptionPlugin);
