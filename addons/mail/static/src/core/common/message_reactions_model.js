// @ts-check
/** @odoo-module native */
import { AND, fields, Record } from "@mail/core/common/record";
import { makeLogger } from "@web/core/debug/debug_logger";
import { rpc } from "@web/core/network";

const log = makeLogger("mail.message.reaction");
export class MessageReactions extends Record {
    static id = AND("message", "content");

    /** @type {string} */
    content;
    /** @type {number} */
    count;
    guests = fields.Many("mail.guest");
    message = fields.One("mail.message");
    partners = fields.Many("res.partner");
    personas = fields.Attr([], {
        /** @this {import("models").MessageReactions} */
        compute() {
            return [...this.partners, ...this.guests];
        },
    });
    /** @type {number} */
    sequence;

    async remove() {
        log.logic("remove", () => ({
            messageId: this.message?.id,
            content: this.content,
        }));
        this.store.insert(
            await rpc(
                "/mail/message/reaction",
                {
                    action: "remove",
                    content: this.content,
                    message_id: this.message.id,
                    ...this.message.thread.rpcParams,
                },
                { silent: true },
            ),
        );
    }
}

MessageReactions.register();
