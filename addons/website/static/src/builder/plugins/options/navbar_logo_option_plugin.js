/** @odoo-module native */
import { BaseOptionComponent } from "@html_builder/core/utils";
import { SNIPPET_SPECIFIC_NEXT } from "@html_builder/utils/option_sequence";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

export class NavbarLogoOption extends BaseOptionComponent {
    static template = "website.NavbarLogoOption";
    static selector = "#wrapwrap > header nav.navbar .navbar-brand";
    static title = _t("Navbar Logo");
    static groups = ["website.group_website_designer"];
    static editableOnly = false;
}

class NavbarLogoOptionPlugin extends Plugin {
    static id = "navbarLogoOptionPlugin";
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [withSequence(SNIPPET_SPECIFIC_NEXT, NavbarLogoOption)],
    };
}

registry
    .category("website-plugins")
    .add(NavbarLogoOptionPlugin.id, NavbarLogoOptionPlugin);
