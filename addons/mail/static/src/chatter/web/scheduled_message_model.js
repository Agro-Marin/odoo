/** @odoo-module native */
import { fields, Record } from "@mail/core/common/record";
import { htmlToTextContentInline } from "@mail/utils/common/format";
import { _t } from "@web/core/l10n/translation";
import { ConnectionAbortedError, ConnectionLostError } from "@web/core/network/rpc";
export class ScheduledMessage extends Record {
    static _name = "mail.scheduled.message";
    static id = "id";
    /** @type {Object.<number, import("models").ScheduledMessage>} */
    static records = {};
    /** @returns {import("models").ScheduledMessage} */
    static get(data) {
        return super.get(data);
    }
    /** @type {number} */
    id;
    attachment_ids = fields.Many("ir.attachment");
    author_id = fields.One("res.partner");
    body = fields.Html("");
    /** @type {boolean} */
    composition_batch;
    scheduled_date = fields.Datetime();
    /** @type {boolean} */
    is_note;
    /** @type {string} sent by the server in _to_store_defaults; rendered in the UI */
    subject;
    textContent = fields.Attr(false, {
        compute() {
            if (!this.body) {
                return "";
            }
            return htmlToTextContentInline(this.body);
        },
    });
    thread = fields.One("Thread");
    // Editors of the records can delete scheduled messages
    get deletable() {
        return this.store.self.main_user_id?.is_admin || this.thread.hasWriteAccess;
    }

    get editable() {
        return this.store.self.main_user_id?.is_admin || this.isSelfAuthored;
    }

    get isSelfAuthored() {
        return this.author_id.eq(this.store.self);
    }

    get isSubjectThreadName() {
        return (
            this.thread?.display_name?.trim().toLowerCase() ===
            this.subject?.trim().toLowerCase()
        );
    }

    /**
     * Cancel the scheduled message.
     */
    async cancel() {
        await this.store.env.services.orm.unlink("mail.scheduled.message", [this.id]);
        this.delete();
    }

    /**
     * Open the mail_compose_mesage form view to allow edition of the scheduled message.
     * If the message has already been sent, displays a notification instead.
     */
    async edit() {
        let action;
        try {
            action = await this.store.env.services.orm.call(
                "mail.scheduled.message",
                "open_edit_form",
                [this.id],
            );
        } catch (e) {
            // Only a server-side business error means the record is gone
            // (already sent / deleted). A transient connection failure must not
            // be reported as "already sent" — re-throw so it surfaces normally.
            if (
                e instanceof ConnectionLostError ||
                e instanceof ConnectionAbortedError
            ) {
                throw e;
            }
            this.notifyAlreadySent();
            return;
        }
        return new Promise((resolve) =>
            this.store.env.services.action.doAction(action, { onClose: resolve }),
        );
    }

    notifyAlreadySent() {
        this.store.env.services.notification.add(
            _t("This message has already been sent."),
            {
                type: "warning",
            },
        );
    }

    /**
     * Send the scheduled message directly
     */
    async send() {
        try {
            await this.store.env.services.orm.call(
                "mail.scheduled.message",
                "post_message",
                [this.id],
            );
        } catch (e) {
            // A server-side business error means already sent (by someone else
            // or by cron) — swallow. A transient connection failure must not be
            // silently ignored: re-throw it.
            if (
                e instanceof ConnectionLostError ||
                e instanceof ConnectionAbortedError
            ) {
                throw e;
            }
            return;
        }
    }
}

ScheduledMessage.register();
