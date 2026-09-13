/** @odoo-module native */
import { SNIPPET_SPECIFIC_NEXT } from "@html_builder/utils/option_sequence";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { MegaMenuOption } from "@website/builder/plugins/options/mega_menu_option";

const log = makeLogger("website.builder.plugin.mega_menu_option_plugin");

/**
 * @typedef { Object } MegaMenuOptionShared
 * @property { MegaMenuOptionPlugin['getTemplatePrefix'] } getTemplatePrefix
 */

const STRUCTURAL_CLASSES = ["dropdown-menu", "o_mega_menu", "o_editable"];

const EDITOR_STATE_CLASSES = ["o_dirty"];

export class MegaMenuOptionPlugin extends Plugin {
    static id = "megaMenuOptionPlugin";
    static dependencies = [];
    static shared = ["getTemplatePrefix"];

    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [withSequence(SNIPPET_SPECIFIC_NEXT, MegaMenuOption)],
        dropzone_selector: {
            selector: ".o_mega_menu .nav > .nav-link",
            dropIn: ".o_mega_menu nav",
            dropNear: ".o_mega_menu .nav-link",
        },
        save_handlers: this.saveMegaMenuClasses.bind(this),
        no_parent_containers: ".o_mega_menu",
        is_unremovable_selector: ".o_mega_menu > section",
        unsplittable_node_predicates: (node) =>
            node?.nodeType === Node.ELEMENT_NODE &&
            node.matches(".o_mega_menu .nav > .nav-link"),
    };

    getTemplatePrefix() {
        return "website.";
    }

    async saveMegaMenuClasses() {
        const proms = [];
        for (const megaMenuEl of this.editable.querySelectorAll(
            "[data-oe-field='mega_menu_content']",
        )) {
            const classes = [...megaMenuEl.classList].filter(
                (megaMenuClass) =>
                    !STRUCTURAL_CLASSES.includes(megaMenuClass) &&
                    !EDITOR_STATE_CLASSES.includes(megaMenuClass),
            );

            proms.push(
                this.services.orm.write(
                    "website.menu",
                    [parseInt(megaMenuEl.dataset.oeId)],
                    {
                        mega_menu_classes: classes.join(" "),
                    },
                ),
            );
        }
        log.pipeline("MegaMenuOptionPlugin save classes", () => ({
            menus: proms.length,
        }));
        const endWrite = log.perf(
            "MegaMenuOptionPlugin write mega_menu_classes",
            () => ({
                menus: proms.length,
            }),
        );
        await Promise.all(proms);
        endWrite();
    }
}

registry.category("website-plugins").add(MegaMenuOptionPlugin.id, MegaMenuOptionPlugin);
