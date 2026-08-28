/** @odoo-module native */
import { markRaw, reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";

import { Meeting } from "./meeting.js";

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
                this.env.services["discuss.rtc"]?.channel?.openChatWindow();
            },
        );
    }

    get isNativePipAvailable() {
        return Boolean(window.documentPictureInPicture);
    }

    closePip() {
        this.state.active = false;
        this.pipWindow?.close();
    }

    /**
     * @param {Object} [param0]
     * @param {Component} [param0.context]
     */
    async openPip({ context }) {
        const rtc = this.env.services["discuss.rtc"];
        if (!rtc?.channel) {
            return;
        }
        this.state.active = true;
        const isShadowRoot = context?.root?.el?.getRootNode() instanceof ShadowRoot;
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
