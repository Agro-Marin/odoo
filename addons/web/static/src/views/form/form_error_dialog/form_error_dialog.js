// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { useAction } from "@web/core/action_port";
import { Dialog } from "@web/ui/dialog/dialog";

export class FormErrorDialog extends Component {
    static template = "web.FormErrorDialog";
    static components = { Dialog };
    static props = {
        message: { type: String, optional: true },
        data: { type: Object },
        onDiscard: Function,
        onStayHere: Function,
        onRedirect: { type: Function, optional: true },
        close: Function,
    };

    /** @type {import("@web/core/action_port").ActionPort} */
    action;

    setup() {
        this.action = useAction();
        this.message = this.props.message;
        if (this.props?.data.name === "odoo.exceptions.RedirectWarning") {
            this.message = this.props.data.arguments[0];
            this.redirectAction = this.props.data.arguments[1];
            this.redirectBtnLabel = this.props.data.arguments[2];
            this.additionalContext = this.props.data.arguments[3];
        }
    }

    /** @returns {Promise<void>} */
    async onRedirectBtnClicked() {
        if (this.props.onRedirect) {
            await this.props.onRedirect({
                action: this.redirectAction,
                additionalContext: this.additionalContext,
            });
            this.props.close();
        } else {
            await this.action.doAction(this.redirectAction, {
                additionalContext: this.additionalContext,
                forceLeave: true,
            });
            this.stay();
        }
    }

    /** @returns {Promise<void>} */
    async discard() {
        await this.props.onDiscard();
        this.props.close();
    }

    /** @returns {Promise<void>} */
    async stay() {
        await this.props.onStayHere();
        this.props.close();
    }
}
