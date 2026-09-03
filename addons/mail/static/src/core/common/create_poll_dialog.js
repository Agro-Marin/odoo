/** @odoo-module native */
import { CreatePollOption } from "@mail/core/common/create_poll_option";
import { Component, useState } from "@odoo/owl";
import { rpc } from "@web/core/network";
import { useAutofocus } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog";

/**
 * @typedef {Object} Props
 * @property {import("models").Thread} thread
 * @property {() => void} [close]
 * @extends {Component<Props, import("@web/env").OdooEnv>}
 */
export class CreatePollDialog extends Component {
    static template = "mail.CreatePollDialog";
    static components = { CreatePollOption, Dialog };
    static props = ["close?", "thread?"];

    setup() {
        super.setup();
        useAutofocus({ refName: "question" });
        this.state = useState({
            allowMultipleOptions: false,
            duration: "10",
            options: [{ label: "" }, { label: "" }],
            question: "",
            submitted: false,
        });
    }

    onClickAddOption() {
        this.state.options.push({ label: "" });
    }

    /** @param {number} index */
    onClickRemoveOption(index) {
        this.state.options.splice(index, 1);
    }

    async onClickSubmit() {
        this.state.submitted = true;
        if (this.optionsMissing || this.questionMissing) {
            return;
        }
        await rpc("/mail/poll/create", {
            allow_multiple_options: this.state.allowMultipleOptions,
            duration: parseInt(this.state.duration),
            option_labels: this.state.options
                .map(({ label }) => label.trim())
                .filter(Boolean),
            question: this.state.question.trim(),
            thread_id: this.props.thread.id,
            thread_model: this.props.thread.model,
        });
        this.props.close();
    }

    get optionsMissing() {
        return (
            this.state.submitted &&
            this.state.options.filter(({ label }) => Boolean(label.trim())).length < 2
        );
    }

    get questionMissing() {
        return this.state.submitted && !this.state.question?.trim();
    }
}
