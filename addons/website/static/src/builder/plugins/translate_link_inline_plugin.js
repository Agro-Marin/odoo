/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { selectElements } from "@html_editor/utils/dom_traversal";
import { registry } from "@web/core/registry";

export class TranslateLinkInlinePlugin extends Plugin {
    static id = "translateLinkInline";
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        create_link_handlers: (linkEl) => linkEl.classList.add("o_translate_inline"),
        before_insert_processors: (container) => {
            this.markTranslateInline(container);
            return container;
        },
        on_replaced_media_handlers: ({ newMediaEl }) => {
            this.markTranslateInline(newMediaEl);
        },
        on_snippet_dropped_handlers: ({ snippetEl }) => {
            // a link inside .o_not_editable (s_table_of_content's navbar) is
            // not editable in translation mode either
            for (const linkEl of selectElements(snippetEl, "a")) {
                if (!linkEl.closest(".o_not_editable")) {
                    linkEl.classList.add("o_translate_inline");
                }
            }
        },
    };

    /** @param {Element} containerEl */
    markTranslateInline(containerEl) {
        for (const linkEl of containerEl.querySelectorAll("a")) {
            linkEl.classList.add("o_translate_inline");
        }
    }
}

registry
    .category("website-plugins")
    .add(TranslateLinkInlinePlugin.id, TranslateLinkInlinePlugin);
