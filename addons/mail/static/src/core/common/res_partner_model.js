/** @odoo-module native */
import { IM_STATUS_DEBOUNCE_DELAY } from "@mail/core/common/constants";
import { fields, Record } from "@mail/core/common/record";
import { luxon } from "@web/core/l10n/luxon";
import { debounce } from "@web/core/utils/timing";
import { imageUrl } from "@web/core/utils/urls";
const { DateTime } = luxon;

export class ResPartner extends Record {
    static id = "id";
    static _name = "res.partner";
    static new() {
        /** @type {import("models").ResPartner} */
        const record = super.new(...arguments);
        record.debouncedSetImStatus = debounce(
            /** @param {string} newStatus */
            (newStatus) => record.updateImStatus(newStatus),
            IM_STATUS_DEBOUNCE_DELAY,
        );
        return record;
    }

    _triggerPresenceSubscription = fields.Attr(null, {
        /** @this {import("models").ResPartner} */
        compute() {
            return this.monitorPresence && this.presenceChannel;
        },
        /** @this {import("models").ResPartner} */
        onUpdate() {
            if (this.previousPresencechannel) {
                this.store.env.services.bus_service.deleteChannel(
                    this.previousPresencechannel,
                );
            }
            if (this._triggerPresenceSubscription) {
                this.store.env.services.bus_service.addChannel(this.presenceChannel);
                this.previousPresencechannel = this.presenceChannel;
            } else {
                this.previousPresencechannel = undefined;
            }
        },
    });
    /** @type {string} */
    avatar_128_access_token;
    /** @type {string} */
    commercial_company_name;
    country_id = fields.One("res.country");
    /** @type {(newStatus: string) => void} */
    debouncedSetImStatus;
    /** @type {string} */
    email;
    /** @type {string} */
    function;
    group_ids = fields.Many("res.groups", { inverse: "partners" });
    /** @type {number} */
    id;
    /** @type {ImStatus} */
    im_status = fields.Attr(null, {
        /** @this {import("models").ResPartner} */
        onUpdate() {
            if (this.eq(this.store.self_partner) && this.im_status === "offline") {
                this.store.env.services.im_status.updateBusPresence();
            }
        },
    });
    /** @type {string|undefined} */
    im_status_access_token;
    /** @type {boolean | undefined} */
    is_company;
    /** @type {boolean} */
    is_public;
    main_user_id = fields.One("res.users");
    monitorPresence = fields.Attr(false, {
        /** @this {import("models").ResPartner} */
        compute() {
            if (!this.store.env.services.bus_service.isActive || this.id <= 0) {
                return false;
            }
            return this.im_status !== "im_partner" && !this.is_public;
        },
    });
    /** @type {string} */
    name;
    /** @type {string} */
    display_name;
    /** @type {string} */
    phone;
    /** @type {luxon.DateTime} */
    offline_since = fields.Datetime();
    presenceChannel = fields.Attr(null, {
        /** @this {import("models").ResPartner} */
        compute() {
            const channel = `odoo-presence-res.partner_${this.id}`;
            if (this.im_status_access_token) {
                return channel + `-${this.im_status_access_token}`;
            }
            return channel;
        },
    });
    /** @type {string|undefined} */
    previousPresencechannel;
    write_date = fields.Datetime();

    _computeDisplayName() {
        return this.name || this.display_name;
    }

    get avatarUrl() {
        const accessTokenParam = {};
        if (this.store.self_partner?.main_user_id?.share !== false) {
            accessTokenParam.access_token = this.avatar_128_access_token;
        }
        return imageUrl("res.partner", this.id, "avatar_128", {
            ...accessTokenParam,
            unique: this.write_date,
        });
    }

    get displayName() {
        return this._computeDisplayName();
    }

    searchChat() {
        return Object.values(this.store.Thread.records).find((thread) =>
            thread.isChatWith(this),
        );
    }

    /** @param {string} newStatus */
    updateImStatus(newStatus) {
        if (newStatus === "offline") {
            this.offline_since = DateTime.now();
        }
        this.im_status = newStatus;
    }
}

ResPartner.register();
