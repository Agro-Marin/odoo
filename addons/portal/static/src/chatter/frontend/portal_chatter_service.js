/** @odoo-module native */
import { loadCssFromBundle } from "@mail/utils/common/misc";
import { App } from "@odoo/owl";
import { PortalChatter } from "@portal/chatter/frontend/portal_chatter";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { getTemplate } from "@web/core/templates";
import { appTranslateFn } from "@web/core/translation";
import { session } from "@web/session";

export class PortalChatterService {
    constructor(env, services) {
        this.setup(env, services);
    }

    setup(env, services) {
        this.store = services["mail.store"];
        this.busService = services.bus_service;
    }

    async createShadow(root) {
        const shadow = root.attachShadow({ mode: "open" });
        await loadCssFromBundle(shadow, "portal.assets_chatter_style");
        return shadow;
    }

    async initialize(env) {
        const chatterEl = document.querySelector(".o_portal_chatter");
        if (!chatterEl) {
            odoo.portalChatterReady.resolve(false);
            return;
        }
        const props = {
            resId: parseInt(chatterEl.getAttribute("data-res_id"), 10),
            resModel: chatterEl.getAttribute("data-res_model"),
            composer:
                parseInt(chatterEl.getAttribute("data-allow_composer"), 10) &&
                (chatterEl.getAttribute("data-token") || !session.is_public),
            twoColumns: chatterEl.getAttribute("data-two_columns") === "true",
            displayRating: chatterEl.getAttribute("data-display_rating") === "True",
        };
        const root = document.createElement("div");
        root.setAttribute("id", "chatterRoot");
        if (props.twoColumns) {
            root.classList.add("p-0");
        }
        chatterEl.appendChild(root);
        const thread = this.store.Thread.insert({ model: props.resModel, id: props.resId });
        Object.assign(thread, {
            access_token: chatterEl.getAttribute("data-token"),
            hash: chatterEl.getAttribute("data-hash"),
            pid: parseInt(chatterEl.getAttribute("data-pid"), 10),
        });
        const [shadow, data] = await Promise.all([
            this.createShadow(root),
            rpc(
                "/portal/chatter_init",
                {
                    thread_model: props.resModel,
                    thread_id: props.resId,
                    ...thread.rpcParams,
                },
                { silent: true }
            ),
        ]);
        this.store.insert(data);
        new App(PortalChatter, {
            env,
            getTemplate,
            props,
            translatableAttributes: ["data-tooltip"],
            translateFn: appTranslateFn,
            dev: env.debug,
        }).mount(shadow);
        odoo.portalChatterReady.resolve(true);
    }
}

export const portalChatterService = {
    dependencies: ["mail.store", "bus_service"],
    start(env, services) {
        const portalChatter = new PortalChatterService(env, services);
        portalChatter.initialize(env).catch((error) => {
            odoo.portalChatterReady.resolve(false);
            console.error("Portal chatter failed to initialize", error);
        });
        return portalChatter;
    },
};
registry.category("services").add("portal.chatter", portalChatterService);
