/** @odoo-module native */
import { fields, Record } from "@mail/core/common/record";
import { _t } from "@web/core/translation";
export class Notification extends Record {
    static _name = "mail.notification";
    static id = "id";

    /** @type {number} */
    id;
    mail_message_id = fields.One("mail.message", {
        /** @this {import("models").Notification} */
        onDelete() {
            this.delete();
        },
    });
    /** @type {string} */
    notification_status;
    /** @type {string} */
    notification_type;
    /** @type {string} */
    mail_email_address;
    failure = fields.One("Failure", {
        inverse: "notifications",
        /** @this {import("models").Notification} */
        compute() {
            if (!this.mail_message_id?.isSelfAuthored || !this.isFailure) {
                return false;
            }
            const thread = this.mail_message_id?.thread;
            const channelPart = thread?.isChannelKind ? thread.id : "";
            return {
                id: `${this.notification_type},${thread?.model ?? ""},${channelPart}`,
            };
        },
    });
    /** @type {string} */
    failure_type;
    get failureMessage() {
        switch (this.failure_type) {
            case "mail_smtp":
                return _t("Connection failed");
            case "mail_server_unauthorized":
                return _t("Mail server not available");
            case "mail_bounce":
                return _t("Bounce");
            case "mail_email_invalid":
                return _t("Invalid email address");
            case "mail_email_missing":
                return _t("Missing email address");
            case "mail_from_invalid":
                return _t("Invalid from address");
            case "mail_from_missing":
                return _t("Missing from address");
            case "mail_spam":
                return _t("Detected As Spam");
            default:
                return _t("Exception");
        }
    }
    res_partner_id = fields.One("res.partner");

    /** @returns {string} */
    get autoCanceledFailureType() {
        switch (this.failure_type) {
            case "mail_bl":
                return _t("Blacklisted Address");
            case "mail_dup":
                return _t("Duplicated Email");
            case "mail_optout":
                return _t("Opted Out");
        }
        return "";
    }

    get isFailure() {
        return ["exception", "bounce"].includes(this.notification_status);
    }

    get icon() {
        if (this.isFailure) {
            return "fa-solid fa-envelope";
        }
        return "fa-regular fa-envelope";
    }

    get label() {
        return "";
    }

    get isFollowerNotification() {
        return (
            this.res_partner_id &&
            this.mail_message_id.thread.followers.some(
                (follower) => follower.partner_id.id === this.res_partner_id.id,
            )
        );
    }

    get statusIcon() {
        switch (this.notification_status) {
            case "process":
                return "fa-solid fa-hourglass-half";
            case "pending":
                return "fa-regular fa-paper-plane";
            case "sent":
                return "fa-solid fa-check";
            case "bounce":
                return "fa-solid fa-exclamation";
            case "exception":
                return "fa-solid fa-times text-danger";
            case "ready":
                return "fa-regular fa-paper-plane";
            case "canceled":
                if (this.autoCanceledFailureType) {
                    return "fa-solid fa-xmark";
                }
                return "fa-regular fa-trash-can";
        }
        return "";
    }

    get statusTitle() {
        switch (this.notification_status) {
            case "process":
                return _t("Processing");
            case "pending":
                return _t("Sent");
            case "sent":
                return _t("Delivered");
            case "bounce":
                return _t("Bounced");
            case "exception":
                return _t("Error");
            case "ready":
                return _t("Queued");
            case "canceled":
                return this.autoCanceledFailureType || _t("Cancelled");
        }
        return "";
    }
}

Notification.register();
