// @ts-check
/** @odoo-module native */
import { fields, Record } from "@mail/core/common/record";
import { htmlToTextContentInline } from "@mail/utils/common/format";
import { makeLogger } from "@web/core/debug/debug_logger";
import { RPCError } from "@web/core/network";
import { _t } from "@web/core/translation";

const log = makeLogger("mail.scheduled_message");

const ALREADY_SENT_EXCEPTION = "odoo.exceptions.MissingError";
export class ScheduledMessage extends Record {
    static _name = "mail.scheduled.message";
    static id = "id";
    /** @type {Object.<string, import("models").ScheduledMessage>} */
    static records = {};
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
    /** @type {string} */
    subject;
    textContent = fields.Attr("", {
        /** @this {import("models").ScheduledMessage} */
        compute() {
            if (!this.body) {
                return "";
            }
            return htmlToTextContentInline(this.body);
        },
    });
    thread = fields.One("Thread");
    get deletable() {
        return this.store.selfIsAdmin || this.thread.hasWriteAccess;
    }

    get editable() {
        return this.store.selfIsAdmin || this.isSelfAuthored;
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

    async cancel() {
        log.logic("cancel", () => ({ id: this.id, thread: this.thread?.localId }));
        await this.store.env.services.orm.unlink("mail.scheduled.message", [this.id]);
        this.delete();
    }

    async edit() {
        let action;
        log.logic("edit", () => ({ id: this.id }));
        try {
            action = await this.store.env.services.orm.call(
                "mail.scheduled.message",
                "open_edit_form",
                [this.id],
            );
        } catch (e) {
            this.handleServerError(e);
            return;
        }
        return new Promise((resolve) =>
            this.store.env.services.action.doAction(action, { onClose: resolve }),
        );
    }

    /** @param {Error} error */
    handleServerError(error) {
        if (!(error instanceof RPCError)) {
            throw error;
        }
        log.logic("handleServerError", () => ({
            id: this.id,
            exceptionName: error.exceptionName,
        }));
        if (error.exceptionName === ALREADY_SENT_EXCEPTION) {
            this.notifyAlreadySent();
            return;
        }
        this.store.env.services.notification.add(error.data?.message || error.message, {
            type: "danger",
        });
    }

    notifyAlreadySent() {
        this.store.env.services.notification.add(
            _t("This message has already been sent."),
            {
                type: "warning",
            },
        );
    }

    async send() {
        log.logic("send", () => ({ id: this.id, thread: this.thread?.localId }));
        try {
            await this.store.env.services.orm.call(
                "mail.scheduled.message",
                "post_message",
                [this.id],
            );
        } catch (e) {
            this.handleServerError(e);
        }
    }
}

ScheduledMessage.register();
