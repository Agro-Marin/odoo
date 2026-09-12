// @ts-check
/** @odoo-module native */
import { PresenceMixin } from "@mail/core/common/presence_mixin";
import { fields, Record } from "@mail/core/common/record";
import { imageUrl } from "@web/core/utils/urls";

export class ResPartner extends PresenceMixin(Record) {
    static id = "id";
    static _name = "res.partner";
    /** @type {boolean} */
    active;
    /** @type {string} */
    lang_name;
    /** @type {string} */
    commercial_company_name;
    country_id = fields.One("res.country");
    /** @type {string} */
    email;
    /** @type {string} */
    function;
    group_ids = fields.Many("res.groups", { inverse: "partners" });
    /** @type {boolean | undefined} */
    is_company;
    /** @type {boolean} */
    is_public;
    main_user_id = fields.One("res.users");
    /** @type {string} */
    name;
    /** @type {string} */
    display_name;
    /** @type {string} */
    phone;

    get isSelfPresence() {
        return this.eq(this.store.self_partner);
    }

    computeMonitorPresence() {
        return (
            super.computeMonitorPresence() &&
            this.im_status !== "im_partner" &&
            !this.is_public
        );
    }

    _computeDisplayName() {
        return this.name || this.display_name;
    }

    get avatarUrl() {
        return imageUrl("res.partner", this.id, "avatar_128", {
            ...this.avatarAccessTokenParam,
            unique: this.write_date,
        });
    }

    get displayName() {
        return this._computeDisplayName();
    }

    /** @this {import("models").ResPartner} */
    searchChat() {
        return Object.values(this.store.Thread.records).find((thread) =>
            thread.isChatWith(this),
        );
    }
}

ResPartner.register();
