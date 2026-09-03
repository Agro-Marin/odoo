/** @odoo-module native */
import { fields, Record } from "@mail/core/common/record";

export class MailPollOption extends Record {
    static id = "id";
    static _name = "mail.poll.option";

    /** @type {number} */
    id;
    /** @type {number} */
    number_of_votes;
    /** @type {string} */
    option_label;
    poll_id = fields.One("mail.poll");
    /** @type {boolean} */
    selected_by_self;
    /** @type {number} */
    vote_percentage;
}
MailPollOption.register();
