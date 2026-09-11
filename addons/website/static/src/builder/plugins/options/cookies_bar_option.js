/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { BaseOptionComponent } from "@html_builder/core/utils";
import { Plugin } from "@html_editor/plugin";
import { registry } from "@web/core/registry";
import { renderToElement } from "@web/core/utils/render";

/**
 * @typedef { Object } CookiesBarOptionShared
 * @property { CookiesBarOptionPlugin['getSavedSelectors'] } getSavedSelectors
 */

export class CookiesBarOption extends BaseOptionComponent {
    static template = "website.CookiesBarOption";
    static selector = "#website_cookies_bar";
    static applyTo = ".modal";
}
class CookiesBarOptionPlugin extends Plugin {
    static id = "CookiesBarOptionPlugin";
    static shared = ["getSavedSelectors"];
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [CookiesBarOption],
        builder_actions: {
            SelectLayoutAction,
        },
    };

    setup() {
        this.savedSelectors = {};
    }

    getSavedSelectors() {
        return this.savedSelectors;
    }
}

export class SelectLayoutAction extends BuilderAction {
    static id = "selectLayout";
    static dependencies = ["CookiesBarOptionPlugin"];
    apply({ editingElement, value: layout }) {
        const savedSelectors =
            this.dependencies.CookiesBarOptionPlugin.getSavedSelectors();
        const templateEl = renderToElement(`website.cookies_bar.${layout}`, {
            websiteId: this.services.website.currentWebsite.id,
        });
        const contentEl = editingElement.querySelector(".modal-content");

        const selectorsToKeep = [
            ".o_cookies_bar_text_button",
            ".o_cookies_bar_text_button_essential",
            ".o_cookies_bar_text_title",
            ".o_cookies_bar_text_primary",
            ".o_cookies_bar_text_secondary",
            ".o_cookies_bar_text_policy",
        ];

        for (const selector of selectorsToKeep) {
            const currentLayoutEls = contentEl.querySelector(selector)?.childNodes;
            const newLayoutEl = templateEl.querySelector(selector);
            if (currentLayoutEls && currentLayoutEls.length) {
                savedSelectors[selector] = [...currentLayoutEls];
            }
            const savedSelector = savedSelectors[selector];
            if (newLayoutEl && savedSelector?.length) {
                newLayoutEl.replaceChildren(...savedSelector);
            }
        }

        contentEl.replaceChildren(templateEl);

        switch (layout) {
            case "discrete":
            case "classic":
                editingElement.classList.add("s_popup_bottom");
                this.getDialogEl(editingElement).classList.add("s_popup_size_full");
                break;
            case "popup":
                editingElement.classList.add("s_popup_middle");
                break;
        }
    }
    clean({ editingElement }) {
        const positionClasses = ["s_popup_top", "s_popup_middle", "s_popup_bottom"];
        const sizeClasses = ["modal-sm", "modal-lg", "modal-xl", "s_popup_size_full"];
        editingElement.classList.remove(...positionClasses);
        this.getDialogEl(editingElement).classList.remove(...sizeClasses);
    }
    getDialogEl(editingElement) {
        return editingElement.querySelector(".modal-dialog");
    }
}

registry
    .category("website-plugins")
    .add(CookiesBarOptionPlugin.id, CookiesBarOptionPlugin);
