// @ts-check
/** @odoo-module native */

import { Component, useState } from "@odoo/owl";
import { DomainSelector } from "@web/components/domain_selector/domain_selector";
import { Domain } from "@web/core/domain";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { useConfirmButton } from "@web/ui/dialog/confirm_button_hook";
import { Dialog } from "@web/ui/dialog/dialog";

export class DomainSelectorDialog extends Component {
    static template = "web.DomainSelectorDialog";
    static components = {
        Dialog,
        DomainSelector,
    };
    static props = {
        close: Function,
        onConfirm: Function,
        resModel: String,
        className: { type: String, optional: true },
        defaultConnector: {
            type: [{ value: "&" }, { value: "|" }],
            optional: true,
        },
        domain: String,
        isDebugMode: { type: Boolean, optional: true },
        readonly: { type: Boolean, optional: true },
        text: { type: String, optional: true },
        confirmButtonText: { type: String, optional: true },
        disableConfirmButton: { type: Function, optional: true },
        discardButtonText: { type: String, optional: true },
        title: { type: String, optional: true },
        context: { type: Object, optional: true },
    };
    static defaultProps = {
        isDebugMode: false,
        readonly: false,
        context: {},
    };

    /** @type {(disabled: boolean) => void} */
    setConfirmDisabled;
    /** @type {import("services").ServiceFactories["notification"]} */
    notification;
    /** @type {{ domain: any }} */
    state;

    setup() {
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.state = useState({ domain: this.props.domain });
        this.setConfirmDisabled = useConfirmButton();
    }

    get confirmButtonText() {
        return this.props.confirmButtonText || _t("Confirm");
    }

    get dialogTitle() {
        return this.props.title || _t("Domain");
    }

    get disabled() {
        if (this.props.disableConfirmButton) {
            return this.props.disableConfirmButton(this.state.domain);
        }
        return false;
    }

    get discardButtonText() {
        return this.props.discardButtonText || _t("Discard");
    }

    get domainSelectorProps() {
        return {
            className: this.props.className,
            resModel: this.props.resModel,
            readonly: this.props.readonly,
            isDebugMode: this.props.isDebugMode,
            defaultConnector: this.props.defaultConnector,
            domain: this.state.domain,
            update: (/** @type {string} */ domain) => {
                this.state.domain = domain;
            },
        };
    }

    /**
     * @returns {Promise<boolean>}
     */
    async isDomainValid() {
        let domain;
        try {
            domain = new Domain(this.state.domain).toList({
                ...user.context,
                ...this.props.context,
            });
        } catch {
            return false;
        }
        try {
            return await rpc("/web/domain/validate", {
                model: this.props.resModel,
                domain,
            });
        } catch {
            return false;
        }
    }

    async onConfirm() {
        this.setConfirmDisabled(true);
        let valid;
        try {
            valid = await this.isDomainValid();
        } finally {
            this.setConfirmDisabled(false);
        }
        if (!valid) {
            this.notification.add(_t("Domain is invalid. Please correct it"), {
                type: "danger",
            });
            return;
        }
        this.props.onConfirm(this.state.domain);
        this.props.close();
    }

    onDiscard() {
        this.props.close();
    }
}
