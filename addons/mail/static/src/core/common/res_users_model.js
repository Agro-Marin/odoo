/** @odoo-module native */
import { fields, Record } from "@mail/core/common/record";
import { markup } from "@odoo/owl";
import { createElementWithContent } from "@web/core/utils/dom/html";

export class ResUsers extends Record {
    static _name = "res.users";
    static id = "id";

    /** @type {number} */
    id;
    company_id = fields.One("res.company");
    /** @type {string} */
    get email() {
        return this.partner_id?.email;
    }
    /** @type {string} */
    im_status;
    /** @type {boolean} */
    is_admin;
    /** @type {string} */
    get name() {
        return this.partner_id?.name;
    }
    /** @type {"email" | "inbox"} */
    notification_type;
    partner_id = fields.One("res.partner");
    /** @type {string} */
    get phone() {
        return this.partner_id?.phone;
    }
    /** @type {boolean} */
    share;
    /** @type {ReturnType<import("@odoo/owl").markup>|string|undefined} */
    signature = fields.Html(undefined);
    /** @type {Promise<import("models").ResPartner|undefined>|undefined} */
    _partnerFetch;

    /** @returns {Promise<import("models").ResPartner|undefined>} */
    fetchPartner() {
        if (this.partner_id) {
            return Promise.resolve(this.partner_id);
        }
        this._partnerFetch ??= this.store.env.services.orm.silent
            .read("res.users", [this.id], ["partner_id"], {
                context: { active_test: false },
            })
            .then(([userData]) => {
                if (userData?.partner_id) {
                    this.partner_id = userData.partner_id[0];
                }
                return this.partner_id;
            })
            .finally(() => (this._partnerFetch = undefined));
        return this._partnerFetch;
    }

    getSignatureBlock() {
        if (!this.signature) {
            return "";
        }
        const divElement = document.createElement("div");
        divElement.setAttribute("data-o-mail-quote", "1");
        divElement.append(
            document.createTextNode("-- "),
            document.createElement("br"),
            ...createElementWithContent("div", this.signature).childNodes,
        );
        return markup(divElement.outerHTML);
    }
}

ResUsers.register();
