/** @odoo-module native */
import { SNIPPET_SPECIFIC_NEXT } from "@html_builder/utils/option_sequence";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { registry } from "@web/core/registry";
import { MegaMenuOption } from "@website/builder/plugins/options/mega_menu_option";

/**
 * @typedef { Object } MegaMenuOptionShared
 * @property { MegaMenuOptionPlugin['getTemplatePrefix'] } getTemplatePrefix
 */

// Part of the widget's structure rather than of the user's styling choices, so
// never part of the stored value.
const STRUCTURAL_CLASSES = ["dropdown-menu", "o_mega_menu", "o_editable"];

// Editor state that happens to be spelled as a class. `save_plugin` strips
// `o_dirty` from the CLONE it persists and deliberately leaves it on the live
// element until that element's write has actually succeeded -- so anything
// reading a live `classList` sees it. This writer does exactly that, from its
// own `orm.write` outside the save pipeline, and was storing the editor's dirty
// marker into `mega_menu_classes`: a class that then came back on the next
// load, on a record the user never marked dirty.
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
            node.matches(".o_mega_menu .nav > .nav-link"), //avoid merge
    };

    getTemplatePrefix() {
        return "website.";
    }

    async saveMegaMenuClasses() {
        const proms = [];
        for (const megaMenuEl of this.editable.querySelectorAll(
            "[data-oe-field='mega_menu_content']",
        )) {
            // On top of saving the mega menu content like any other field
            // content, we must save the custom classes that were set on the
            // menu itself.
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
        await Promise.all(proms);
    }
}

registry.category("website-plugins").add(MegaMenuOptionPlugin.id, MegaMenuOptionPlugin);
