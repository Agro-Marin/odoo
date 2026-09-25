// @ts-check
/** @odoo-module native */

import { _t } from "@web/core/translation";
import { voiceExecutorRegistry } from "@voice/executor";

const COMPOSER_BUTTONS = {
    log_note: ".o-mail-Chatter-logNote",
    compose_message: ".o-mail-Chatter-sendMessage",
};

/**
 * The same button the user would press opens the composer, and the words go
 * in after whatever it already held; posting stays the user's.
 *
 * @param {import("@voice/interpreter/interpreter").Proposal} proposal
 * @param {import("@voice/executor").ExecutionContext} context
 */
export async function writeInChatter(proposal, context) {
    const { controller } = context.targetView(proposal);
    const record = controller.model.root;
    if (!record.resId) {
        throw new Error(_t("Save the record before writing in its chatter."));
    }
    const button = controller.rootRef.el?.querySelector(
        COMPOSER_BUTTONS[/** @type {keyof COMPOSER_BUTTONS} */ (proposal.kind)],
    );
    if (!button) {
        throw new Error(_t("This record has no chatter to write in."));
    }
    if (button.disabled) {
        throw new Error(_t("The chatter is still loading; say it again in a moment."));
    }
    if (!button.classList.contains("active")) {
        button.click();
    }
    const thread = context
        .getService("mail.store")
        .Thread.insert({ model: record.resModel, id: record.resId });
    const composer = thread.composer;
    const before = composer.composerText;
    composer.composerText = before ? `${before} ${proposal.text}` : proposal.text;
    return () => {
        composer.composerText = before;
    };
}

voiceExecutorRegistry.add("log_note", writeInChatter);
voiceExecutorRegistry.add("compose_message", writeInChatter);
