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

        window.parent.document.addEventListener(
            "transfer_website_edit_service",
            this.updateEditInteraction.bind(this),
            { once: true }
        );
        const event = new CustomEvent("edit_interaction_plugin_loaded");
        event.shared = this.__editor.shared;
        // Store on the document so late-starting services can find it
        // (the iframe's OWL services may not have started yet).
        window.parent.document.__editInteractionPluginEvent = event;
        window.parent.document.dispatchEvent(event);
    }
    destroy() {
        delete window.parent.document.__editInteractionPluginEvent;
        this.websiteEditService?.uninstallPatches?.();
        // Guard: editor may be destroyed before the cross-frame service
        // transfer completed (e.g. rapid open/close of the editor).
        if (this.websiteEditService) {
            this.stopInteractions();
        }
    }

    updateEditInteraction({ detail: { websiteEditService } }) {
        this.websiteEditService = websiteEditService;
        this.websiteEditService.installPatches();
    }

    restartInteractions(element) {
        if (!this.websiteEditService) {
            return;
        }
        this.websiteEditService.update(element, "edit");
    }

    refreshInteractions(element) {
        if (!this.websiteEditService) {
            return;
        }
        this.websiteEditService.refresh(element);
    }

    stopInteractions(element) {
        if (!this.websiteEditService) {
            return;
        }
        this.websiteEditService.stop(element);
    }

    stopInteraction(name) {
        if (!this.websiteEditService) {
            return;
        }
        this.websiteEditService.stopInteraction(name);
    }
}

registry.category("website-plugins").add(EditInteractionPlugin.id, EditInteractionPlugin);
