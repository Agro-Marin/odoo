/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";

/**
 * @typedef {import("@html_editor/core/user_command_plugin").UserCommand} UserCommand
 * @typedef {((url: string) => UserCommand)[]} paste_media_url_command_providers
 */

export class MediaUrlPastePlugin extends Plugin {
    static id = "mediaUrlPaste";
    static dependencies = ["link", "dom", "history", "powerbox"];
    /** @type {import("plugins").EditorResources} */
    resources = {
        paste_url_overrides: this.openPowerboxOnUrlPaste.bind(this),

        /** Handlers */
        post_undo_handlers: this.closePowerbox.bind(this),
    };

    /**
     * @param {string} text
     * @param {string} url
     */
    openPowerboxOnUrlPaste(text, url) {
        const commands = this.getResource("paste_media_url_command_providers")
            .map((provider) => provider(url))
            .filter(Boolean);
        if (commands.length) {
            commands.push(this.dependencies.link.getPathAsUrlCommand(text, url));
            const restoreSavepoint = this.dependencies.history.makeSavePoint();
            this.dependencies.dom.insert(text);
            this.dependencies.history.addStep();
            this.dependencies.powerbox.openPowerbox({
                commands,
                onApplyCommand: restoreSavepoint,
                onClose: () => (this.isPowerboxOpen = false),
            });
            this.isPowerboxOpen = true;
            return true;
        }
    }

    /**
     * An undo reverts the pasted text the powerbox was offering commands for,
     * so its commands no longer have a target. Close it -- but only if it is
     * ours, since any other plugin's powerbox is none of our business.
     */
    closePowerbox() {
        if (this.isPowerboxOpen) {
            this.dependencies.powerbox.closePowerbox();
        }
    }
}
