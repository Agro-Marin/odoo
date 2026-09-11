// @ts-check
/** @odoo-module native */
import { IM_STATUS_DEBOUNCE_DELAY } from "@mail/core/common/constants";
import { fields, Record } from "@mail/core/common/record";
import { toRaw } from "@odoo/owl";
import { luxon } from "@web/core/l10n/luxon";
import { debounce } from "@web/core/utils/timing";
import { imageUrl } from "@web/core/utils/urls";
const { DateTime } = luxon;

export class ResPartner extends Record {
    static id = "id";
    static _name = "res.partner";
    /** @type {boolean} */
    active;
    /** @type {string} */
    lang_name;
    /**
     * @template {typeof Record} T
     * @this {T}
     * @param {import("@mail/model/record").RecordData} data
     * @param {import("@mail/model/record").RecordData} ids
     * @returns {InstanceType<T>}
     */
    static new(data, ids) {
        /** @type {import("models").ResPartner} */
        const record = /** @type {import("models").ResPartner} */ (
            /** @type {unknown} */ (super.new(data, ids))
        );
        record.debouncedSetImStatus = debounce(
            /** @param {import("./mail_guest_model").ImStatus} newStatus */
            (newStatus) => record.updateImStatus(newStatus),
            IM_STATUS_DEBOUNCE_DELAY,
        );
        return /** @type {InstanceType<T>} */ (/** @type {unknown} */ (record));
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
    /** @type {ReturnType<typeof debounce<(newStatus: import("./mail_guest_model").ImStatus) => void>>} */
    debouncedSetImStatus;
    /** @type {string} */
    email;
    /** @type {string} */
    function;
    group_ids = fields.Many("res.groups", { inverse: "partners" });
    /** @type {number} */
    id;
    /** @type {import("./mail_guest_model").ImStatus} */
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
            thread.isChatWith(
                /** @type {import("models").ResPartner} */ (
                    /** @type {unknown} */ (this)
                ),
            ),
        );
    }

    delete() {
        toRaw(this)._raw.debouncedSetImStatus.cancel();
        super.delete();
    }

    /** @param {import("./mail_guest_model").ImStatus} newStatus */
    updateImStatus(newStatus) {
        if (newStatus === "offline") {
            this.offline_since = DateTime.now();
        }
        this.im_status = newStatus;
    }
}

ResPartner.register();
