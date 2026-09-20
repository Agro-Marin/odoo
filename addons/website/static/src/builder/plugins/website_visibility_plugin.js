/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";

import { VisibilityOption } from "./options/visibility_option.js";
import { DEVICE_VISIBILITY_OPTION_SELECTOR } from "./options/visibility_option_plugin.js";

const log = makeLogger("website.builder.plugin.website_visibility_plugin");

export class WebsiteVisibilityPlugin extends Plugin {
    static id = "websiteVisibilityPlugin";

    /** @type {import("plugins").WebsiteResources} */
    resources = {
        system_classes: ["o_conditional_hidden"],
        target_show: this.onTargetShow.bind(this),
        target_hide: this.onTargetHide.bind(this),
    };

    onTargetHide(editingEl) {
        if (
            editingEl.matches(DEVICE_VISIBILITY_OPTION_SELECTOR) ||
            editingEl.matches(VisibilityOption.selector)
        ) {
            editingEl.classList.remove("o_snippet_override_invisible");

            const isConditionalHidden = editingEl.matches(
                "[data-visibility='conditional']",
            );
            log.logic("onTargetHide", () => ({
                snippet: editingEl.dataset.snippet,
                isConditionalHidden,
            }));
            if (isConditionalHidden) {
                editingEl.classList.add("o_conditional_hidden");
            }
        }
    }

    onTargetShow(editingEl) {
        if (
            editingEl.matches(DEVICE_VISIBILITY_OPTION_SELECTOR) ||
            editingEl.matches(VisibilityOption.selector)
        ) {
            const isMobilePreview = this.config.isMobileView(editingEl);
            const isMobileHidden = editingEl.classList.contains(
                "o_snippet_mobile_invisible",
            );
            const isDesktopHidden = editingEl.classList.contains(
                "o_snippet_desktop_invisible",
            );
            log.logic("onTargetShow", () => ({
                snippet: editingEl.dataset.snippet,
                isMobilePreview,
                isMobileHidden,
                isDesktopHidden,
            }));
            if (
                (isMobileHidden && isMobilePreview) ||
                (isDesktopHidden && !isMobilePreview)
            ) {
                editingEl.classList.add("o_snippet_override_invisible");
            }

            editingEl.classList.remove("o_conditional_hidden");
        }
    }
}

registry
    .category("website-plugins")
    .add(WebsiteVisibilityPlugin.id, WebsiteVisibilityPlugin);
