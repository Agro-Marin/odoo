/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { registry } from "@web/core/registry";

/**
 * @typedef { Object } EditInteractionShared
 * @property { EditInteractionPlugin['restartInteractions'] } restartInteractions
 * @property { EditInteractionPlugin['stopInteractions'] } stopInteractions
 */

/**
 * @typedef {((commonAncestorEl: HTMLElement) => void)[]} content_manually_updated_handlers
 */

export class EditInteractionPlugin extends Plugin {
    static id = "edit_interaction";

    static shared = ["restartInteractions", "stopInteraction"];

    /** @type {import("plugins").WebsiteResources} */
    resources = {
        normalize_handlers: this.refreshInteractions.bind(this),
        content_manually_updated_handlers: this.refreshInteractions.bind(this),
        before_save_handlers: withSequence(5, this.stopInteractions.bind(this)),
        after_save_handlers: this.restartInteractions.bind(this),
        on_will_clone_handlers: ({ originalEl }) => {
            this.stopInteractions(originalEl);
        },
        on_cloned_handlers: ({ originalEl }) => {
            this.restartInteractions(originalEl);
            // The clonedEl is implicitly started because it is a newly
            // inserted content.
        },
    };

    setup() {
        this.websiteEditService = undefined;

        this._onTransferEditService = this.updateEditInteraction.bind(this);
        window.parent.document.addEventListener(
            "transfer_website_edit_service",
            this._onTransferEditService,
            { once: true },
        );
        const event = new CustomEvent("edit_interaction_plugin_loaded");
        event.shared = this.__editor.shared;
        window.parent.document.dispatchEvent(event);
    }
    destroy() {
        // If the plugin is destroyed before the event fires, this {once}
        // listener (and the bound handler retaining the plugin) would stay on
        // the long-lived parent document. Removing a spent listener is a no-op.
        window.parent.document.removeEventListener(
            "transfer_website_edit_service",
            this._onTransferEditService,
        );
        this.websiteEditService?.uninstallPatches?.();
        this.stopInteractions();
    }

    updateEditInteraction({ detail: { websiteEditService } }) {
        this.websiteEditService = websiteEditService;
        this.websiteEditService.installPatches();
    }

    restartInteractions(element) {
        if (!this.websiteEditService) {
            throw new Error("website edit service not loaded");
        }
        this.websiteEditService.update(element, "edit");
    }

    refreshInteractions(element) {
        this.websiteEditService.refresh(element);
    }

    stopInteractions(element) {
        if (!this.websiteEditService) {
            throw new Error("website edit service not loaded");
        }
        this.websiteEditService.stop(element);
    }

    stopInteraction(name) {
        if (!this.websiteEditService) {
            throw new Error("website edit service not loaded");
        }
        this.websiteEditService.stopInteraction(name);
    }
}

registry
    .category("website-plugins")
    .add(EditInteractionPlugin.id, EditInteractionPlugin);
