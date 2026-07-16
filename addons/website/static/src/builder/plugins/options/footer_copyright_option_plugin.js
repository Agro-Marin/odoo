/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { registry } from "@web/core/registry";
import { FooterCopyrightOption } from "@website/builder/plugins/options/footer_copyright_option";

class FooterCopyrightOptionPlugin extends Plugin {
    static id = "footerCopyrightOption";

    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [FooterCopyrightOption],
    };
}

registry
    .category("website-plugins")
    .add(FooterCopyrightOptionPlugin.id, FooterCopyrightOptionPlugin);
