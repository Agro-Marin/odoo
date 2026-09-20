// @ts-check
/** @odoo-module native */
import { PresenceMixin } from "@mail/core/common/presence_mixin";
import { fields, Record } from "@mail/core/common/record";
import { makeLogger } from "@web/core/debug/debug_logger";
import { rpc } from "@web/core/network";
import { imageUrl } from "@web/core/utils/urls";

const log = makeLogger("mail.guest");
const TRANSPARENT_AVATAR =
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAQAAABpN6lAAAAAqElEQVR42u3QMQEAAAwCoNm/9GJ4CBHIjYsAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBAgQIAAAQIECBDQ9+KgAIHd5IbMAAAAAElFTkSuQmCC";
/**
 * @typedef {import("@mail/core/common/presence_mixin").ImStatus} ImStatus
 * @typedef Data
 * @property {number} id
 * @property {string} name
 * @property {string} email
 * @property {ImStatus} im_status
 */

export class MailGuest extends PresenceMixin(Record) {
    static id = "id";
    static _name = "mail.guest";

    /** @type {string} */
    name;
    country_id = fields.One("res.country");
    /** @type {string} */
    email;

    get isSelfPresence() {
        return this.eq(this.store.self_guest) && this.id < 0;
    }

    get avatarUrl() {
        if (this.id === -1) {
            return TRANSPARENT_AVATAR;
        }
        return imageUrl("mail.guest", this.id, "avatar_128", {
            ...this.avatarAccessTokenParam,
            unique: this.write_date,
        });
    }

    /** @param {string} name */
    async updateGuestName(name) {
        log.logic("updateGuestName", () => ({ id: this.id }));
        await rpc("/mail/guest/update_name", {
            guest_id: this.id,
            name,
        });
    }
}

MailGuest.register();
