// @ts-check
/** @odoo-module native */
import { markRaw, reactive } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";

import { Meeting } from "./meeting.js";

const log = makeLogger("mail.rtc.pip");

export class CallPipService {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("services").ServiceFactories} services
     */
    constructor(env, services) {
        this.env = env;
        this.popout = services["mail.popout"].createManager(
            Symbol("discuss.native.pip"),
        );
        /** @type {Window|null} */
        this.pipWindow = null;
        this.state = reactive({ active: false });
    }

    setup() {
        this.popout.addHooks(
            () => {},
            () => {
                this.state.active = false;
            },
        );
    }

    get isNativePipAvailable() {
        return Boolean(window.documentPictureInPicture);
    }

    closePip() {
        log.lifecycle("closePip", () => ({ wasActive: this.state.active }));
        this.state.active = false;
        this.pipWindow?.close();
    }

    /**
     * @param {Object} [param0]
     * @param {import("@odoo/owl").Component} [param0.context]
     */
    async openPip({ context } = {}) {
        const rtc = this.env.services["discuss.rtc"];
        if (!rtc?.channel) {
            log.logic("openPip refused: no call");
            return;
        }
        this.state.active = true;
        const isShadowRoot = context?.root?.el?.getRootNode() instanceof ShadowRoot;
        log.lifecycle("openPip", () => ({
            channel: rtc.channel.id,
            native: this.isNativePipAvailable,
            isShadowRoot,
        }));
        const pipWindow = await this.popout.pip(Meeting, {
            props: { isPip: true },
            options: { useAlternativeAssets: isShadowRoot },
        });
        this.pipWindow = markRaw(pipWindow);
        pipWindow.addEventListener(
            "keydown",
            /** @param {KeyboardEvent} ev */ (ev) => {
                rtc.onKeyDown(ev);
            },
        );
        pipWindow.addEventListener(
            "keyup",
            /** @param {KeyboardEvent} ev */ (ev) => {
                rtc.onKeyUp(ev);
            },
        );
        pipWindow.document.body.style.backgroundColor = "black";
        pipWindow.document.body.style.overflow = "hidden";
        pipWindow.document.body.style.display = "block";
    }
}

export const callPipService = {
    dependencies: ["mail.popout"],

    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {import("services").ServiceFactories} services
     */
    start(env, services) {
        const pip = reactive(new CallPipService(env, services));
        pip.setup();
        return pip;
    },
};

registry.category("services").add("discuss.pip_service", callPipService);
