/** @odoo-module native */
import { Component } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

/**
 * What a voice message says, under the player that plays it.
 *
 * @extends {Component<{ attachment: import("models").Attachment }>}
 */
export class VoiceTranscript extends Component {
    static template = "mail_speech.VoiceTranscript";
    static props = { attachment: { type: Object } };

    setup() {
        this.orm = useService("orm");
    }

    /** @returns {boolean} */
    get isPending() {
        return ["queued", "running"].includes(this.props.attachment.speech_state);
    }

    /** @returns {string} */
    get label() {
        if (this.isPending) {
            return _t("Transcribing…");
        }
        if (this.props.attachment.speech_state === "failed") {
            return _t("Could not transcribe");
        }
        return _t("Transcribe");
    }

    async onClickTranscribe() {
        this.props.attachment.speech_state = "queued";
        await this.orm.call("ir.attachment", "action_transcribe", [
            [this.props.attachment.id],
        ]);
    }
}
