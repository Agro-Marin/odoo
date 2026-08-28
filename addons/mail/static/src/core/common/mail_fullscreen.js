/** @odoo-module native */
import { Component, reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
const DEFAULT_ID = Symbol("default");

export class MailFullscreen extends Component {
    static props = ["component", "props?"];
    static template = "mail.Fullscreen";

    setup() {
        super.setup();
        this.fullscreen = useService("mail.fullscreen");
    }
}

export class MailFullscreenService {
    /**
     * @param {import("@web/env").OdooEnv} env
     */
    constructor(env) {
        this.env = env;
        this.id = undefined;
        this.closeOverlay = undefined;
    }

    setup() {
        browser.addEventListener("fullscreenchange", () => {
            const isFullscreen = Boolean(
                document.webkitFullscreenElement || document.fullscreenElement,
            );
            if (!isFullscreen) {
                this.exit();
            }
        });
    }

    /**
     * @param {object} [options]
     * @param {any} [options.id]
     * @param {boolean} [options.keepBrowserHeader]
     * @param {string} [options.rootId]
     * @returns {Promise<void>}
     */
    async enter(
        component,
        { keepBrowserHeader = false, props, rootId, id = DEFAULT_ID } = {},
    ) {
        this.closeOverlay?.();
        this.id = id;
        this.closeOverlay = this.env.services.overlay.add(
            MailFullscreen,
            { component, props },
            { rootId },
        );
        const el = document.body;
        if (keepBrowserHeader) {
            return;
        }
        try {
            if (el.requestFullscreen) {
                await el.requestFullscreen();
            } else if (el.mozRequestFullScreen) {
                await el.mozRequestFullScreen();
            } else if (el.webkitRequestFullscreen) {
                await el.webkitRequestFullscreen();
            }
        } catch {}
    }

    /** @param {any} [id=this.id] */
    async exit(id = this.id) {
        if (!id || id !== this.id) {
            return;
        }
        this.closeOverlay?.();
        this.id = undefined;
        this.closeOverlay = undefined;
        const fullscreenElement =
            document.webkitFullscreenElement || document.fullscreenElement;
        if (fullscreenElement) {
            if (document.exitFullscreen) {
                await document.exitFullscreen();
            } else if (document.mozCancelFullScreen) {
                await document.mozCancelFullScreen();
            } else if (document.webkitCancelFullScreen) {
                await document.webkitCancelFullScreen();
            }
        }
    }
}

export const fullscreenService = {
    /**
     * @param {import("@web/env").OdooEnv} env
     */
    start(env) {
        const fullscreen = reactive(new MailFullscreenService(env));
        fullscreen.setup();
        return fullscreen;
    },
};

registry.category("services").add("mail.fullscreen", fullscreenService);
