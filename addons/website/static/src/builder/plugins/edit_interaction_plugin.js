/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";

const log = makeLogger("website.builder.plugin.edit_interaction");

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
        },
    };

    setup() {
        log.lifecycle("setup");
        this.websiteEditService = undefined;

        this._onTransferEditService = this.updateEditInteraction.bind(this);
        window.parent.document.addEventListener(
            "transfer_website_edit_service",
            this._onTransferEditService,
            { once: true },
        );
        this._offerToEditService = () => {
            if (this._transferred) {
                log.logic("offerToEditService skip: service already transferred");
                return;
            }
            log.pipeline("offerToEditService dispatch edit_interaction_plugin_loaded");
            const event = new CustomEvent("edit_interaction_plugin_loaded");
            event.shared = this.__editor.shared;
            window.parent.document.dispatchEvent(event);
        };
        window.parent.document.addEventListener(
            "website_edit_service_ready",
            this._offerToEditService,
        );
        this._offerToEditService();
    }
    destroy() {
        log.lifecycle("destroy", () => ({
            transferred: !!this._transferred,
            hasEditService: !!this.websiteEditService,
        }));
        window.parent.document.removeEventListener(
            "transfer_website_edit_service",
            this._onTransferEditService,
        );
        window.parent.document.removeEventListener(
            "website_edit_service_ready",
            this._offerToEditService,
        );
        this.websiteEditService?.uninstallPatches?.();
        this.stopInteractions();
    }

    updateEditInteraction({ detail: { websiteEditService } }) {
        log.lifecycle("updateEditInteraction edit service transferred", () => ({
            refreshOwed: !!this._refreshOwed,
        }));
        this._transferred = true;
        this.websiteEditService = websiteEditService;
        this.websiteEditService.installPatches();
        if (this._refreshOwed) {
            log.pipeline("updateEditInteraction flush owed refresh");
            this._refreshOwed = false;
            this.websiteEditService.refresh(this.editable);
        }
    }

    restartInteractions(element) {
        if (!this.websiteEditService) {
            log.logic("restartInteractions failed: edit service not loaded");
            throw new Error("website edit service not loaded");
        }
        log.pipeline("restartInteractions", () => ({
            tagName: element?.tagName,
            snippet: element?.dataset?.snippet,
        }));
        this.websiteEditService.update(element, "edit");
    }

    refreshInteractions(element) {
        if (!this.websiteEditService) {
            log.logic("refreshInteractions deferred: edit service not transferred yet");
            this._refreshOwed = true;
            return;
        }
        this.websiteEditService.refresh(element);
    }

    stopInteractions(element) {
        if (!this.websiteEditService) {
            log.logic("stopInteractions failed: edit service not loaded");
            throw new Error("website edit service not loaded");
        }
        log.pipeline("stopInteractions", () => ({
            tagName: element?.tagName,
            snippet: element?.dataset?.snippet,
        }));
        this.websiteEditService.stop(element);
    }

    stopInteraction(name) {
        if (!this.websiteEditService) {
            log.logic("stopInteraction failed: edit service not loaded", { name });
            throw new Error("website edit service not loaded");
        }
        log.pipeline("stopInteraction", { name });
        this.websiteEditService.stopInteraction(name);
    }
}

registry
    .category("website-plugins")
    .add(EditInteractionPlugin.id, EditInteractionPlugin);
