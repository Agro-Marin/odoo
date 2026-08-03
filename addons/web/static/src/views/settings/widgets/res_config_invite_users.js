// @ts-check
/** @odoo-module native */

/** @module @web/views/settings/widgets/res_config_invite_users */

import { Component, onWillStart, useState } from "@odoo/owl";
import { useAction } from "@web/core/action_port";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { unique } from "@web/core/utils/collections/arrays";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
class ResConfigInviteUsers extends Component {
    static template = "res_config_invite_users";
    static props = {
        ...standardWidgetProps,
    };

    /** @type {import("@web/core/action_port").ActionPort} */
    action;
    /** @type {import("services").ServiceFactories["user_invite"]} */
    invite;
    /** @type {import("services").ServiceFactories["notification"]} */
    notification;
    /** @type {import("services").ServiceFactories["orm"]} */
    orm;
    /** @type {{ status: string; emails: string; invite: null }} */
    state;

    setup() {
        this.orm = useService("orm");
        this.invite = useService("user_invite");
        this.action = useAction();
        this.notification = useService("notification");

        this.state = useState({
            status: "idle",
            emails: "",
            invite: null,
        });

        onWillStart(async () => {
            this.state.invite = await this.invite.fetchData();
        });
    }

    /**
     * @param {string} email
     * @returns {boolean}
     */
    validateEmail(email) {
        const re =
            /^([a-z0-9][-a-z0-9_+.]*)@((?:[\w-]+\.)*\w[\w-]{0,66})\.([a-z]{2,63}(?:\.[a-z]{2})?)$/i;
        return re.test(email);
    }

    get emails() {
        return unique(
            this.state.emails
                .split(/[ ,;\n]+/)
                .map((email) => email.trim())
                .filter((email) => email.length),
        );
    }

    validate() {
        if (!this.emails.length) {
            throw new Error(_t("Empty email address"));
        }
        const invalidEmails = [];
        for (const email of this.emails) {
            if (!this.validateEmail(email)) {
                invalidEmails.push(email);
            }
        }
        if (invalidEmails.length) {
            const errorMessage = (() => {
                switch (invalidEmails.length) {
                    case 1:
                        return _t("Invalid email address: %(address)s", {
                            address: invalidEmails[0],
                        });
                    case 2:
                        return _t("Invalid email addresses: %(two_addresses)s", {
                            two_addresses: invalidEmails,
                        });
                    default:
                        return _t("Invalid email addresses: %(addresses)s", {
                            addresses: invalidEmails,
                        });
                }
            })();
            throw new Error(errorMessage);
        }
    }

    get inviteButtonText() {
        if (this.state.status === "inviting") {
            return _t("Inviting...");
        }
        return _t("Invite");
    }

    onClickMore(ev) {
        this.action.doAction(this.state.invite.action_pending_users);
    }

    onClickUser(ev, user) {
        const action = { ...this.state.invite.action_pending_users, res_id: user[0] };
        this.action.doAction(action);
    }

    onKeydownUserEmails(ev) {
        const keys = ["Enter", "Tab", ","];
        if (keys.includes(ev.key)) {
            if (ev.key === "Tab" && !this.emails.length) {
                return;
            }
            ev.preventDefault();
            this.sendInvite();
        }
    }

    /** @private */
    async sendInvite() {
        if (this.state.status === "inviting") {
            return;
        }
        try {
            this.validate();
        } catch (e) {
            this.notification.add(e.message, { type: "danger" });
            return;
        }

        this.state.status = "inviting";

        const pendingUserEmails = this.state.invite.pending_users.map(
            (user) => user[1],
        );
        const emailsLeftToProcess = this.emails.filter(
            (email) => !pendingUserEmails.includes(email),
        );

        try {
            if (emailsLeftToProcess.length) {
                await this.orm.call("res.users", "web_create_users", [
                    emailsLeftToProcess,
                ]);
                this.state.invite = await this.invite.fetchData(true);
            } else {
                this.notification.add(
                    _t("All email addresses already have a pending invitation."),
                    { type: "info" },
                );
            }
            this.state.emails = "";
        } finally {
            this.state.status = "idle";
        }
    }
}

/** @type {import("registries").ViewWidgetsRegistryItemShape} */
export const resConfigInviteUsers = {
    component: ResConfigInviteUsers,
};

registry.category("view_widgets").add("res_config_invite_users", resConfigInviteUsers);
